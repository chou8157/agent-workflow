#!/usr/bin/env python3
"""按版本预检和连续升级既有工作流，保留已有文档与历史日期。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import task_context
from scaffold_workflow import CAPABILITY_DEPENDS, CAPABILITY_PATHS


WORKFLOW_DIR = ".agent-workflow"
VERSION_FILE = "WORKFLOW_VERSION"
SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = SKILL_ROOT / "assets" / "templates"
WORKFLOW_TEMPLATE = TEMPLATE_ROOT / WORKFLOW_DIR
VERSION_STEPS = {
    2: "补齐多工作项入口，历史公共记录保留原位置。",
    3: "将无冲突旧工作项迁移为本地 .state.json，未知历史日期保持未知。",
    4: "保留已有交付资料；仅维护已使用的可选能力，不发布或搬迁历史交付物。",
    5: "依据已有能力清单或实际存在的模块补齐结构，不自动启用新模块。",
    6: "补齐连续升级和本地活动规则；既有入口只生成增量建议。",
}
V6_MARKER = "<!-- agent-workflow:versioned-upgrade-v6 -->"


def read_latest_version() -> int:
    path = WORKFLOW_TEMPLATE / VERSION_FILE
    try:
        version = int(path.read_text(encoding="utf-8").strip())
        if version not in VERSION_STEPS:
            raise ValueError("模板版本没有对应升级步骤")
        return version
    except (OSError, ValueError) as error:
        raise RuntimeError(f"内置工作流版本文件无效：{path}") from error


LATEST_VERSION = read_latest_version()


def workflow_path(project: Path) -> Path:
    return project / WORKFLOW_DIR


def check_path(project: Path, path: Path, kind: str = "file") -> None:
    relative = path.relative_to(project)
    cursor = project
    for index, part in enumerate(relative.parts):
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"升级路径不能包含符号链接：{cursor}")
        expected = kind if index == len(relative.parts) - 1 else "directory"
        if cursor.exists() and not (cursor.is_dir() if expected == "directory" else cursor.is_file()):
            raise ValueError(f"升级路径类型冲突：{cursor}")


def read_structure_version(project: Path) -> int:
    version_file = workflow_path(project) / VERSION_FILE
    check_path(project, version_file)
    if not version_file.exists():
        return 1
    text = version_file.read_text(encoding="utf-8").strip()
    if not text.isascii() or not text.isdecimal() or text.startswith("0"):
        raise ValueError(f"工作流版本文件无效：{version_file}")
    version = int(text)
    if version > LATEST_VERSION:
        raise ValueError(f"项目工作流版本 {version} 高于当前脚本支持的版本 {LATEST_VERSION}，请更新技能后再检查。")
    return version


def suggestion_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.agent-workflow-v{LATEST_VERSION}-suggestion")


def review_targets(project: Path) -> list[dict[str, str]]:
    workflow = workflow_path(project)
    candidates = [
        (project / "AGENTS.md", "work-items/", "需求、任务和缺陷的独立上下文位于 `.agent-workflow/30-records/work-items/`；多个进行中工作项而用户未指定目标时必须先询问。"),
        (workflow / "README.md", "30-records/work-items/", "涉及实际开发需求时，先选择 `30-records/work-items/<ID>/`，再读取其入口、当前状态和需求定义。"),
        (workflow / "00-core/disclosure.md", "目标工作项", "读取项目公共状态后，选择目标工作项，再读取其 `README.md`、`current-status.md` 和 `work-item.md`；详细历史按需读取。"),
    ]
    additions: dict[Path, list[str]] = {}
    for target, marker, content in candidates:
        check_path(project, target)
        if target.is_file() and marker not in target.read_text(encoding="utf-8"):
            additions.setdefault(target, []).append(content)
    for target in (project / "AGENTS.md", workflow / "README.md", workflow / "00-core/workflow.md"):
        check_path(project, target)
        if target.is_file() and V6_MARKER not in target.read_text(encoding="utf-8"):
            additions.setdefault(target, []).append(
                V6_MARKER + "\n版本升级和本地活动规则见 `.agent-workflow/00-core/versioning.md`（从工作流目录内读取时为 `00-core/versioning.md`）。"
                "使用当前统一安装的 agent-workflow 写入器；升级先只读预检，明确执行 apply-safe 后迁移。"
                "实际工作只在本项目记录活动，旧历史日期缺失时保持未知，跨项目关联按需启用。"
            )
    reviews = []
    for target, paragraphs in additions.items():
        suggestion = suggestion_path(target)
        check_path(project, suggestion)
        reviews.append({"target": str(target), "suggestion": str(suggestion), "content": "## 工作流升级增量建议\n\n" + "\n\n".join(paragraphs) + "\n"})
    return reviews


def capability_plan(project: Path) -> tuple[list[str], dict | None]:
    workflow = workflow_path(project)
    manifest = workflow / ".capabilities.json"
    check_path(project, manifest)
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("enabled"), list):
            raise ValueError("能力清单格式无效，不能自动替换")
        enabled = data["enabled"]
        if any(not isinstance(name, str) or name not in CAPABILITY_PATHS for name in enabled):
            raise ValueError("能力清单包含未知能力，不能自动替换")
        if "version" in data and (type(data["version"]) is not int or data["version"] != 1):
            raise ValueError("能力清单版本不受支持，不能自动替换")
        completed = list(dict.fromkeys(["core", "work-items"] + enabled))
        for name in completed:
            for dependency in CAPABILITY_DEPENDS[name]:
                if dependency not in completed:
                    completed.append(dependency)
        if set(completed) != set(enabled):
            return completed, dict(data, enabled=completed)
        return completed, None
    enabled = ["core", "work-items"]
    for name, paths in CAPABILITY_PATHS.items():
        if name not in enabled and paths and any((workflow / rel).exists() for rel in paths):
            enabled.append(name)
    for name in enabled:
        for dependency in CAPABILITY_DEPENDS[name]:
            if dependency not in enabled:
                enabled.append(dependency)
    return enabled, {"version": 1, "enabled": enabled, "inferred_from": "existing_paths"}


def build_upgrade_plan(project: Path) -> dict[str, object]:
    project = Path(project).resolve()
    workflow = workflow_path(project)
    check_path(project, workflow, "directory")
    if not workflow.is_dir():
        raise ValueError(".agent-workflow/ 不存在，请先初始化项目工作流。")
    current_version = read_structure_version(project)
    actions: list[dict] = []
    conflicts: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    migrations: list[dict[str, str]] = []
    structure_checked = False
    try:
        check_path(project, workflow / ".upgrade.lock")
        enabled, manifest = capability_plan(project)
        required = {"AGENTS.md": TEMPLATE_ROOT / "AGENTS.md"}
        for capability in enabled:
            for rel in CAPABILITY_PATHS[capability]:
                source = WORKFLOW_TEMPLATE / rel
                if source.is_dir():
                    check_path(project, workflow / rel, "directory")
                    for child in sorted(source.rglob("*")):
                        if child.is_file():
                            required[str(Path(WORKFLOW_DIR) / child.relative_to(WORKFLOW_TEMPLATE))] = child
                else:
                    required[str(Path(WORKFLOW_DIR) / rel)] = source
        for rel, source in required.items():
            if source.name == VERSION_FILE:
                continue
            target = project / rel
            check_path(project, target)
            if not target.exists():
                if not source.is_file():
                    raise ValueError(f"升级模板不存在：{source}")
                actions.append({"action": "copy_template", "source": str(source), "target": str(target), "message": "补齐已启用能力的缺失结构。"})
        if manifest is not None:
            actions.append({"action": "write_capabilities", "target": str(workflow / ".capabilities.json"), "payload": manifest, "replace": (workflow / ".capabilities.json").exists(), "message": "登记已有能力并补齐声明能力的必需依赖。"})
        reviews = review_targets(project)
        structure_checked = True
        for finding in task_context.migration_report(project):
            if finding["finding"] == "缺少状态文件":
                migrations.append({"action": "migrate_state", "target": str(task_context.work_items_dir(project) / finding["id"] / task_context.STATE_FILENAME), "id": finding["id"], "message": "迁移合法旧状态，保留原文档与未知日期。"})
            else:
                conflicts.append(finding)
    except (ValueError, OSError, UnicodeError) as error:
        conflicts.append({"finding": str(error)})
    structure_actions = list(actions)
    if current_version < LATEST_VERSION:
        actions.append({"action": "write_version", "target": str(workflow / VERSION_FILE), "message": f"全部结构和状态迁移完成后记录结构版本 {LATEST_VERSION}。"})
    structure_up_to_date = structure_checked and current_version == LATEST_VERSION and not structure_actions
    ready = not conflicts and not migrations and not structure_actions
    return {
        "project": str(project), "current_version": current_version, "latest_version": LATEST_VERSION,
        "version_source": "file" if (workflow / VERSION_FILE).exists() else "legacy_unversioned",
        "version_path": list(range(current_version, LATEST_VERSION + 1)),
        "version_steps": [{"from": version - 1, "to": version, "message": VERSION_STEPS[version]} for version in range(current_version + 1, LATEST_VERSION + 1)],
        "safe_actions": actions, "migration_actions": migrations, "review_actions": reviews, "conflicts": conflicts,
        "can_apply": not conflicts, "structure_up_to_date": structure_up_to_date,
        "migration_pending": bool(migrations), "review_pending": bool(reviews), "runtime_ready": ready,
        "up_to_date": structure_up_to_date and ready and not reviews,
    }


def write_atomic(path: Path, content: bytes, replace: bool = False) -> bool:
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".upgrade-", suffix=".tmp", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                return False
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def apply_safe_upgrade(project: Path) -> dict[str, object]:
    project = Path(project).resolve()
    plan = build_upgrade_plan(project)
    if not plan["can_apply"]:
        plan.update({"applied": False, "created_suggestions": [], "migrated_states": []})
        return plan
    created_suggestions = []
    migrated = []
    with task_context.state_lock(workflow_path(project) / ".upgrade"):
        plan = build_upgrade_plan(project)
        if not plan["can_apply"]:
            plan.update({"applied": False, "created_suggestions": [], "migrated_states": []})
            return plan
        # 最后才记录版本；中断后重跑仅继续补缺，不重新写已有状态或文档。
        for action in plan["safe_actions"]:
            target = Path(action["target"])
            check_path(project, target)
            if action["action"] == "write_version":
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            content = Path(action["source"]).read_bytes() if action["action"] == "copy_template" else (json.dumps(action["payload"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            write_atomic(target, content, replace=action.get("replace", False))
        migrated = [str(path) for path in task_context.migrate_legacy_items(project)]
        for review in plan["review_actions"]:
            suggestion = Path(review["suggestion"])
            check_path(project, suggestion)
            if write_atomic(suggestion, review["content"].encode("utf-8")):
                created_suggestions.append(str(suggestion))
        checked = build_upgrade_plan(project)
        if checked["conflicts"] or checked["migration_actions"] or any(action["action"] != "write_version" for action in checked["safe_actions"]):
            raise ValueError("升级后检查未通过，未推进版本标记；请重新运行 plan 排查。")
        if read_structure_version(project) != LATEST_VERSION:
            write_atomic(workflow_path(project) / VERSION_FILE, f"{LATEST_VERSION}\n".encode("ascii"), replace=True)
    result = build_upgrade_plan(project)
    result.update({"applied": True, "created_suggestions": created_suggestions, "migrated_states": migrated})
    return result


def format_plan(plan: dict[str, object]) -> str:
    lines = [f"项目：{plan['project']}", f"工作流结构版本：{plan['current_version']} -> {plan['latest_version']}", "升级路径：" + " -> ".join(str(version) for version in plan["version_path"])]
    for key, title in (("safe_actions", "安全补缺"), ("migration_actions", "状态迁移"), ("review_actions", "文档待审"), ("conflicts", "阻断问题")):
        lines.append(title + "：" + ("" if plan[key] else "无。"))
        for item in plan[key]:
            lines.append("- " + (f"{item['target']}，建议文件：{item['suggestion']}" if key == "review_actions" else item.get("message", item.get("finding", ""))))
    lines.append(f"可执行安全升级：{'是' if plan['can_apply'] else '否'}；结构最新：{'是' if plan['structure_up_to_date'] else '否'}；已全部完成：{'是' if plan['up_to_date'] else '否'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".", help="项目控制根目录。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (("status", "只读查看版本、迁移和审阅状态。"), ("plan", "只读生成连续版本升级计划。"), ("apply-safe", "整体预检后补缺和迁移，不覆盖已有文档。")):
        subparsers.add_parser(command, help=help_text).add_argument("--json", action="store_true", help="输出机器可读 JSON。")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"项目目录不存在：{project}", file=sys.stderr)
        return 2
    try:
        result = apply_safe_upgrade(project) if args.command == "apply-safe" else build_upgrade_plan(project)
    except (ValueError, OSError, UnicodeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_plan(result))
    return 0 if result["can_apply"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
