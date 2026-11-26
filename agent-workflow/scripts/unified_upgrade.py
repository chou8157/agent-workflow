#!/usr/bin/env python3
"""统一检查和执行 agent-workflow 工具及项目升级。

本入口只编排已有的安装更新器和项目升级器，不替换旧命令，也不自动下载、
扫描或迁移未指定的项目。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import upgrade_workflow
import document_baseline
import project_upgrade_transaction


def _load_release_update():
    """加载完整发行包中的更新器，源码仓库中回退到 experiments/frontier。"""
    try:
        return importlib.import_module("release_update")
    except ImportError:
        frontier = Path(__file__).resolve().parents[2] / "experiments" / "frontier"
        if not frontier.is_dir():
            raise ValueError("当前运行包不包含技能安装更新器")
        sys.path.insert(0, str(frontier))
        return importlib.import_module("release_update")


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _tree_fingerprint(root: Path) -> str:
    """记录项目当前内容，避免计划生成后静默覆盖用户修改。"""
    root = root.resolve()
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (".git" in relative.parts or "__pycache__" in relative.parts or ".pytest_cache" in relative.parts or
                ".upgrade-transactions" in relative.parts or relative.name == ".upgrade-transaction.lock"):
            continue
        if path.is_symlink():
            entries.append({"path": relative.as_posix(), "kind": "symlink", "target": str(path.readlink())})
        elif path.is_file():
            entries.append({"path": relative.as_posix(), "kind": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        elif path.is_dir():
            entries.append({"path": relative.as_posix(), "kind": "directory"})
    return _fingerprint(entries)


def _not_checked(reason: str) -> dict[str, Any]:
    return {"status": "not_checked", "reason": reason}


def _tool_plan(package: Path | None, skills_root: Path | None) -> dict[str, Any]:
    if package is None and skills_root is None:
        return _not_checked("未指定候选包和 skills 根目录")
    if package is None or skills_root is None:
        return {"status": "blocked", "error": "工具升级必须同时指定 --package 和 --skills-root"}
    try:
        updater = _load_release_update()
        return updater.update_plan(package, skills_root)
    except (ImportError, OSError, ValueError, UnicodeError) as error:
        return {"status": "blocked", "error": str(error)}


def build_plan(project: Path | None = None, package: Path | None = None,
               skills_root: Path | None = None) -> dict[str, Any]:
    if project is None and package is None and skills_root is None:
        raise ValueError("至少指定 --project，或同时指定 --package 和 --skills-root")

    tool = _tool_plan(package, skills_root)
    project_result: dict[str, Any]
    if project is None:
        project_result = _not_checked("未指定项目")
    else:
        try:
            project_result = upgrade_workflow.build_upgrade_plan(project)
            document_result = document_baseline.build_plan(project)
            project_result["documents"] = document_result
            transaction_result = project_upgrade_transaction.build_plan(project, project_result, document_result)
            project_result["transaction"] = transaction_result
            project_result["up_to_date"] = bool(project_result.get("up_to_date")) and bool(document_result.get("up_to_date")) and transaction_result["status"] != "blocked"
            project_result["project_fingerprint"] = _tree_fingerprint(project)
        except (OSError, ValueError, UnicodeError) as error:
            project_result = {"status": "blocked", "error": str(error), "project": str(project.resolve())}

    payload: dict[str, Any] = {"tool": tool, "project": project_result}
    payload["plan_fingerprint"] = _fingerprint(payload)
    return payload


def summarize(plan: dict[str, Any]) -> dict[str, Any]:
    pending: list[str] = []
    blockers: list[str] = []
    checked: list[str] = []

    tool = plan["tool"]
    if tool.get("status") == "not_checked":
        pass
    elif tool.get("status") == "blocked":
        blockers.append("工具升级：" + str(tool.get("error", "预检失败")))
        checked.append("tool")
    elif tool.get("status") == "planned":
        pending.append("工具更新")
        checked.append("tool")
    elif tool.get("status") == "unchanged":
        checked.append("tool")

    project = plan["project"]
    if project.get("status") == "not_checked":
        pass
    elif project.get("status") == "blocked":
        blockers.append("项目升级：" + str(project.get("error", "预检失败")))
        checked.append("project")
    else:
        checked.append("project")
        if project.get("conflicts"):
            blockers.extend("项目升级：" + str(item.get("finding", item)) for item in project["conflicts"])
        if project.get("documents", {}).get("conflicts"):
            blockers.extend("文档合并：" + str(item.get("finding", item)) for item in project["documents"]["conflicts"])
        if project.get("transaction", {}).get("status") == "blocked":
            blockers.append("项目升级：存在未完成事务，请先恢复")
        elif not project.get("up_to_date", False):
            pending.append("项目工作流升级或文档审阅")

    if blockers:
        status, exit_code = "blocked", 3
    elif pending:
        status, exit_code = "pending", 2
    elif checked:
        status, exit_code = "complete", 0
    else:
        status, exit_code = "not_checked", 3

    return {"status": status, "exit_code": exit_code, "checked": checked,
            "pending": pending, "blockers": blockers,
            "plan_fingerprint": plan["plan_fingerprint"]}


def apply_plan(plan: dict[str, Any], project: Path | None, package: Path | None,
               skills_root: Path | None, update_tool: bool, upgrade_project: bool,
               writers_stopped: bool) -> dict[str, Any]:
    current_plan = build_plan(project=project, package=package, skills_root=skills_root)
    if current_plan["plan_fingerprint"] != plan["plan_fingerprint"]:
        raise ValueError("当前内容已变化，旧计划指纹失效；请重新生成计划")
    summary = summarize(plan)
    if summary["blockers"]:
        return {"status": "blocked", "summary": summary, "results": {}}

    results: dict[str, Any] = {}
    try:
        if update_tool:
            if package is None or skills_root is None:
                raise ValueError("执行工具更新必须同时指定 --package 和 --skills-root")
            tool = plan["tool"]
            if tool.get("status") == "not_checked":
                raise ValueError("工具更新缺少有效计划")
            updater = _load_release_update()
            if tool.get("status") == "unchanged":
                results["tool"] = {"status": "unchanged", "path": tool.get("path"),
                                    "current": tool.get("current")}
            else:
                results["tool"] = updater.update(
                    package, skills_root, tool["expected_current"], tool["expected_source"], writers_stopped
                )

        if upgrade_project:
            if project is None:
                raise ValueError("执行项目升级必须指定 --project")
            project_plan = plan["project"]
            results["project"] = project_upgrade_transaction.apply(
                project,
                project_plan,
                project_plan.get("documents", {}),
                project_plan.get("plan_fingerprint"),
            )
    except (ImportError, OSError, ValueError, UnicodeError) as error:
        results["error"] = str(error)
        return {"status": "failed", "summary": {**summary, "status": "failed", "exit_code": 4},
                "plan_fingerprint": plan["plan_fingerprint"], "results": results}

    after = build_plan(project=project, package=package, skills_root=skills_root)
    after_summary = summarize(after)
    return {"status": after_summary["status"], "summary": after_summary,
            "plan_fingerprint": plan["plan_fingerprint"], "results": results,
            "after": after}


def _format(plan: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = ["统一升级检查：" + summary["status"],
             "计划指纹：" + summary["plan_fingerprint"]]
    for item in summary["pending"]:
        lines.append("- 待处理：" + item)
    for item in summary["blockers"]:
        lines.append("- 已阻断：" + item)
    if not summary["pending"] and not summary["blockers"]:
        lines.append("- 本次范围内无需更新。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("status", "只读查看指定工具和项目的当前状态。"),
        ("plan", "只读生成绑定当前内容的统一升级计划。"),
        ("apply", "按明确指定的范围执行工具更新和/或项目升级。"),
    ):
        command_parser = sub.add_parser(command, help=help_text)
        command_parser.add_argument("--project", type=Path, help="明确指定的项目目录。")
        command_parser.add_argument("--package", type=Path, help="已解压并可校验的候选包目录。")
        command_parser.add_argument("--skills-root", type=Path, help="明确指定的 skills 根目录。")
        command_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")
        if command == "apply":
            command_parser.add_argument("--update-tool", action="store_true", help="执行本机技能包更新。")
            command_parser.add_argument("--upgrade-project", action="store_true", help="执行指定项目的安全升级。")
            command_parser.add_argument("--writers-stopped", action="store_true", help="确认旧/新技能写入项目的 Agent 均已停止。")
            command_parser.add_argument("--plan-fingerprint", help="只执行与已审阅计划一致的内容。")

    recover_parser = sub.add_parser("recover-project", help="恢复指定项目未完成的升级事务。")
    recover_parser.add_argument("--project", type=Path, required=True, help="明确指定的项目目录。")
    recover_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")

    args = parser.parse_args(argv)
    try:
        project = args.project.resolve() if args.project else None
        package = args.package.resolve() if args.package else None
        skills_root = args.skills_root.resolve() if args.skills_root else None
        if args.command == "recover-project":
            result = project_upgrade_transaction.recover(args.project.resolve())
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("项目升级事务恢复：" + result["status"])
            return 0 if result["status"] in ("recovered", "unchanged") else 4

        plan = build_plan(project, package, skills_root)
        summary = summarize(plan)
        if args.command == "apply":
            if not args.update_tool and not args.upgrade_project:
                raise ValueError("apply 必须明确指定 --update-tool 或 --upgrade-project")
            if args.plan_fingerprint and args.plan_fingerprint != plan["plan_fingerprint"]:
                raise ValueError("当前内容已变化，旧计划指纹失效；请重新生成计划")
            result = apply_plan(plan, project, package, skills_root,
                                args.update_tool, args.upgrade_project, args.writers_stopped)
            exit_code = (0 if result["status"] == "complete" else
                         2 if result["status"] == "pending" else
                         3 if result["status"] == "blocked" else 4)
            output = result
        else:
            exit_code = summary["exit_code"]
            output = {"summary": summary, **plan}
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(_format(output.get("after", output), output.get("summary", summary)))
        return exit_code
    except (ImportError, OSError, ValueError, UnicodeError) as error:
        print("统一升级失败：{}".format(error), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
