"""真实工作流的隔离副本试跑；来源只读，输出仅包含脱敏计数和哈希。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if __package__:
    from . import mvp_light, node_workflow
else:
    import mvp_light
    import node_workflow


ROLES = ("root", "middle", "leaf")
TRIAL_DATE = "2026-10-15"
TRIAL_ITEM = "W-trial-20261015"
START, END = "2026-10-12", "2026-10-18"
CLI = Path(__file__).with_name("light_cli.py")


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _manifest(project):
    root = Path(project) / ".agent-workflow"
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        row = {"path_sha256": _hash(relative.encode("utf-8"))}
        if path.is_symlink():
            row.update(kind="symlink", sha256=_hash(os.readlink(path).encode("utf-8")))
        elif path.is_file():
            raw = path.read_bytes()
            row.update(kind="file", sha256=_hash(raw), bytes=len(raw))
        elif path.is_dir():
            row.update(kind="directory")
        else:
            row.update(kind="other")
        rows.append(row)
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"manifest_sha256": _hash(encoded), "file_count": sum(row["kind"] == "file" for row in rows),
            "symlink_count": sum(row["kind"] == "symlink" for row in rows), "entries": rows}


def _safe_source(project, relative):
    relative = Path(relative)
    if (relative.is_absolute() or ".." in relative.parts or not relative.parts or
            relative.parts[0] != ".agent-workflow" or relative.suffix not in (".md", ".json")):
        return None
    path = project / relative
    if any(parent.is_symlink() for parent in (path,) + tuple(path.parents) if parent != project):
        return None
    return path if path.is_file() else None


def _copy_workflow(source, destination):
    """只复制读取工作项所需的四种文件及其显式证据，不复制项目代码。"""
    source, destination = Path(source), Path(destination)
    selected = set()
    items_root = source / node_workflow.ITEMS
    counts = {"work_items": 0, "missing_state": 0, "invalid_state": 0, "activity_records": 0}
    for item in sorted(items_root.glob("W-*")):
        if not item.is_dir() or item.is_symlink():
            continue
        counts["work_items"] += 1
        (destination / item.relative_to(source)).mkdir(parents=True, exist_ok=True)
        for name in node_workflow.DOCUMENTS:
            path = _safe_source(source, (item / name).relative_to(source))
            if path is not None:
                selected.add(path)
        state_path = _safe_source(source, (item / ".state.json").relative_to(source))
        if state_path is None:
            counts["missing_state"] += 1
            continue
        try:
            state = json.loads(state_path.read_bytes())
            node_workflow._stable.validate_state(state, item.name)
        except (ValueError, TypeError, AttributeError, KeyError):
            counts["invalid_state"] += 1
            continue
        records = state.get("activity_records") or []
        if isinstance(records, list):
            counts["activity_records"] += len(records)
            for record in records:
                if not isinstance(record, dict):
                    continue
                for ref in record.get("evidence_refs") or []:
                    if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                        path = _safe_source(source, ref["path"])
                        if path is not None:
                            selected.add(path)
    (destination / node_workflow.ITEMS).mkdir(parents=True, exist_ok=True)
    for relative in (".agent-workflow/README.md", str(node_workflow.ITEMS / "README.md")):
        path = _safe_source(source, relative)
        if path is not None:
            selected.add(path)
    for path in sorted(selected):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    counts["copied_files"] = len(selected)
    return counts


def _run(command, arguments, commands):
    result = subprocess.run([sys.executable, str(CLI), command] + list(map(str, arguments)),
                            capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    commands.append({"command": command, "returncode": result.returncode,
                     "stdout_bytes": len(result.stdout.encode("utf-8")),
                     "stdout_sha256": _hash(result.stdout.encode("utf-8")),
                     "stderr_bytes": len(result.stderr.encode("utf-8")),
                     "stderr_sha256": _hash(result.stderr.encode("utf-8"))})
    return result


def _report(project, nodes, commands):
    command = _run("report", ["--project", project, "--source-root", nodes,
                              "--start", START, "--end", END], commands)
    result = node_workflow.aggregate(project, nodes)
    window = mvp_light.activity_window(result, START, END)
    summary = {"status": result["status"], "returncode": command.returncode,
               "expected_nodes": result["coverage"]["expected"],
               "failed_nodes": sorted(result["coverage"]["failed"]),
               "activity_count": len(window["records"]),
               "trial_activity_count": sum(record["work_item_id"] == TRIAL_ITEM for record in window["records"]),
               "unknown_work_item_count": len(window["unknown_date_work_items"]),
               "unknown_date_notice": "不能判断该范围内是否有工作" in command.stdout,
               "report_sha256": _hash(command.stdout.encode("utf-8"))}
    assert command.returncode == (0 if result["status"] == "full" else 2), "报告退出码与覆盖状态不一致"
    return summary, window


def _record_arguments(project, role, evidence, identifier=None, line=1):
    return ["--project", project, "--item", TRIAL_ITEM, "--id", identifier or "trial-" + role,
            "--date", TRIAL_DATE, "--summary", "隔离副本的结构与只读检查（试验活动）",
            "--status", "completed", "--evidence", evidence,
            "--line-start", line, "--line-end", line]


def run_trial(sources, output):
    if set(sources) != set(ROLES):
        raise ValueError("必须显式指定 root、middle、leaf 三个来源")
    sources = {role: Path(sources[role]).resolve() for role in ROLES}
    if len(set(sources.values())) != 3:
        raise ValueError("三个来源必须是不同项目")
    output = Path(output).resolve()
    for role, source in sources.items():
        if not (source / ".agent-workflow").is_dir() or not (source / node_workflow.ITEMS).is_dir():
            raise ValueError("来源 {} 缺少工作流或工作项目录".format(role))
        if (source / ".agent-workflow").is_symlink() or (source / node_workflow.ITEMS).is_symlink():
            raise ValueError("来源 {} 的工作流入口不能是符号链接".format(role))
        if output == source or source in output.parents:
            raise ValueError("试跑输出必须位于所有来源项目之外")
    before = {role: _manifest(source) for role, source in sources.items()}
    report = {"schema": 1, "trial_date": TRIAL_DATE, "scope": "真实工作流隔离副本；原项目只读；无历史迁移",
              "source_manifest_scope": ".agent-workflow 内全部目录、文件内容和符号链接目标的脱敏哈希",
              "commands": [], "checks": {}, "sources": {}}
    commands, checks = report["commands"], report["checks"]
    failure = None
    try:
        with tempfile.TemporaryDirectory(prefix="frontier-real-trial-", dir="/private/tmp") as directory:
            workspace = Path(directory)
            nodes = workspace / "nodes"
            copies = {role: nodes / role for role in ROLES}
            registry = workspace / "control/registry.sqlite"
            for role in ROLES:
                report["sources"][role] = _copy_workflow(sources[role], copies[role])
                args = ["--project", copies[role], "--node-id", role]
                args += ["--registry", registry] if role == "root" else ["--parent", copies["root" if role == "middle" else "middle"]]
                assert _run("connect", args, commands).returncode == 0, "副本接入失败"
            baseline, window = _report(copies["root"], nodes, commands)
            report["historical_baseline"] = baseline
            historical_count = sum(value["work_items"] for value in report["sources"].values())
            prior_records = sum(value["activity_records"] for value in report["sources"].values())
            checks["historical_dates_not_inferred"] = prior_records != 0 or (
                not window["records"] and baseline["unknown_work_item_count"] == historical_count and
                (historical_count == 0 or baseline["unknown_date_notice"]))
            checks["source_activity_records_absent"] = prior_records == 0
            checks["record_retries_idempotent"] = True
            checks["log_append_keeps_prior_evidence"] = True
            for role in ROLES:
                project = copies[role]
                item = node_workflow._stable.create_work_item(project, TRIAL_ITEM, "隔离副本试跑", "实验", "")
                node_workflow._stable.set_status(project, TRIAL_ITEM, "in_progress")
                evidence = item / "validation-log.md"
                counts = report["sources"][role]
                evidence.write_text("本次为 {} 隔离副本检查：复制 {} 个必要文件，检查 {} 个历史工作项；活动日期 {}。\n".format(
                    role, counts["copied_files"], counts["work_items"], TRIAL_DATE), encoding="utf-8")
                arguments = _record_arguments(project, role, evidence.relative_to(project))
                first = _run("record", arguments, commands)
                state_after_first = (item / ".state.json").read_bytes()
                second = _run("record", arguments, commands)
                checks["record_retries_idempotent"] &= (
                    first.returncode == second.returncode == 0 and "created" in first.stdout and
                    "unchanged" in second.stdout and (item / ".state.json").read_bytes() == state_after_first)
                with evidence.open("a", encoding="utf-8") as stream:
                    stream.write("追加检查：同 ID 重试后状态字节保持不变。\n")
                third = _run("record", arguments, commands)
                checks["log_append_keeps_prior_evidence"] &= (
                    third.returncode == 0 and "unchanged" in third.stdout and
                    (item / ".state.json").read_bytes() == state_after_first)
            reports = {role: _report(copies[role], nodes, commands)[0] for role in ROLES}
            report["hierarchical_reports"] = reports
            checks["root_middle_leaf_aggregation"] = all(
                reports[role]["trial_activity_count"] == expected for role, expected in zip(ROLES, (3, 2, 1)))
            repeated, _ = _report(copies["root"], nodes, commands)
            checks["report_retry_stable"] = repeated == reports["root"]
            broken = node_workflow._stable.create_work_item(copies["leaf"], "W-trial-legacy-gap", "缺口注入试验", "实验", "")
            broken_state = broken / ".state.json"
            saved_state = broken_state.read_bytes()
            broken_state.unlink()
            injected, _ = _report(copies["root"], nodes, commands)
            checks["missing_old_state_is_explicit_partial"] = (
                injected["status"] == "partial" and "leaf" in injected["failed_nodes"] and
                injected["trial_activity_count"] == 3 and injected["returncode"] == 2)
            report["injected_legacy_gap"] = injected
            broken_state.write_bytes(saved_state)
            detached = _run("leave", ["--project", copies["leaf"]], commands)
            parents_before = {role: _manifest(copies[role]) for role in ("root", "middle")}
            registry_before = registry.read_bytes()
            unavailable = registry.with_name("offline.sqlite")
            registry.rename(unavailable)
            evidence = copies["leaf"] / node_workflow.ITEMS / TRIAL_ITEM / "validation-log.md"
            with evidence.open("a", encoding="utf-8") as stream:
                stream.write("退出关联后检查：节点已关闭关联，关系库在副本中暂不可访问。\n")
            independent = _run("record", _record_arguments(copies["leaf"], "leaf", evidence.relative_to(copies["leaf"]),
                                                          "trial-leaf-detached", 3), commands)
            registry_data_unchanged = unavailable.read_bytes() == registry_before
            unavailable.rename(registry)
            leaf_state = node_workflow._stable.read_state(copies["leaf"] / node_workflow.ITEMS / TRIAL_ITEM)
            checks["detached_record_without_registry"] = (
                detached.returncode == independent.returncode == 0 and len(leaf_state["activity_records"]) == 2 and
                not node_workflow.identity(copies["leaf"])["network_enabled"])
            checks["local_record_does_not_write_parents_or_registry"] = registry_data_unchanged and all(
                _manifest(copies[role]) == parents_before[role] for role in parents_before)
            after_leave, _ = _report(copies["root"], nodes, commands)
            report["after_leave"] = after_leave
            checks["leave_removes_node_from_parent_query"] = (
                after_leave["expected_nodes"] == ["middle", "root"] and after_leave["trial_activity_count"] == 2)
    except Exception as error:
        failure = type(error).__name__
    finally:
        after = {role: _manifest(source) for role, source in sources.items()}
        checks["original_workflows_unchanged"] = before == after
        for role in ROLES:
            report["sources"].setdefault(role, {}).update(before=before[role], after=after[role],
                                                       unchanged=before[role] == after[role])
    report["status"] = "passed" if failure is None and all(checks.values()) else "needs_attention"
    report["failure_type"] = failure
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, help="显式来源，格式为 root=目录、middle=目录、leaf=目录")
    parser.add_argument("--output", required=True, type=Path, help="所有来源之外的脱敏 JSON 输出文件")
    args = parser.parse_args(argv)
    try:
        sources = {}
        for value in args.source:
            role, separator, path = value.partition("=")
            if not separator or role not in ROLES or role in sources or not path:
                raise ValueError("来源参数无效或重复")
            sources[role] = Path(path)
        report = run_trial(sources, args.output)
    except Exception as error:
        sys.stderr.write("隔离试跑未开始或无法收口：{}\n".format(type(error).__name__))
        return 2
    sys.stdout.write("隔离试跑：{}；检查 {} 项；原工作流未改动：{}\n".format(
        report["status"], len(report["checks"]), report["checks"]["original_workflows_unchanged"]))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
