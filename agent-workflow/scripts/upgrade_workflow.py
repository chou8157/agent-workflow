#!/usr/bin/env python3
"""安全升级既有 智能体工作流 的目录结构。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


WORKFLOW_DIR = ".agent-workflow"
VERSION_FILE = "WORKFLOW_VERSION"
SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = SKILL_ROOT / "assets" / "templates"
WORKFLOW_TEMPLATE = TEMPLATE_ROOT / WORKFLOW_DIR


def read_latest_version() -> int:
    version_file = WORKFLOW_TEMPLATE / VERSION_FILE
    try:
        return int(version_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as error:
        raise RuntimeError(f"内置工作流版本文件无效：{version_file}") from error


LATEST_VERSION = read_latest_version()


def workflow_path(project: Path) -> Path:
    return project / WORKFLOW_DIR


def read_structure_version(project: Path) -> int:
    version_file = workflow_path(project) / VERSION_FILE
    if not version_file.exists():
        return 1
    try:
        return int(version_file.read_text(encoding="utf-8").strip())
    except ValueError as error:
        raise ValueError(f"工作流版本文件无效：{version_file}") from error


def suggestion_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.agent-workflow-v2-suggestion")


def review_targets(project: Path) -> list[dict[str, str]]:
    candidates = [
        (
            project / "AGENTS.md",
            "work-items/",
            "## 多工作项工作流入口\n\n- 项目公共状态：`.agent-workflow/30-records/current-status.md`。\n- 需求、任务和缺陷的独立上下文：`.agent-workflow/30-records/work-items/`。\n- 多个进行中工作项而用户未指定目标时，必须先询问。\n",
        ),
        (
            workflow_path(project) / "README.md",
            "30-records/work-items/",
            "## 多工作项恢复入口\n\n涉及实际开发需求时，先选择 `30-records/work-items/<ID>/`，再读取该工作项的入口、当前状态和需求定义。项目公共规则和跨任务记录仍只保留一份。\n",
        ),
        (
            workflow_path(project) / "00-core" / "disclosure.md",
            "目标工作项",
            "## 多工作项渐进读取建议\n\n在读取项目公共状态后，选择目标工作项，再读取其 `README.md`、`current-status.md` 和 `work-item.md`。详细任务历史只按需读取该工作项的 `progress/`、`changes/` 和局部日志。\n",
        ),
    ]
    reviews: list[dict[str, str]] = []
    for target, marker, content in candidates:
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        if marker not in text:
            reviews.append(
                {
                    "target": str(target),
                    "suggestion": str(suggestion_path(target)),
                    "content": content,
                }
            )
    return reviews


def build_upgrade_plan(project: Path) -> dict[str, object]:
    workflow = workflow_path(project)
    if not workflow.is_dir():
        raise ValueError(".agent-workflow/ 不存在，请先初始化项目工作流。")

    current_version = read_structure_version(project)
    if current_version > LATEST_VERSION:
        raise ValueError(f"项目工作流版本 {current_version} 高于当前脚本支持的版本 {LATEST_VERSION}。")

    safe_actions: list[dict[str, str]] = []
    target = workflow / "30-records" / "work-items" / "README.md"
    if not target.exists():
        safe_actions.append(
            {
                "action": "copy_template",
                "source": str(WORKFLOW_TEMPLATE / "30-records" / "work-items" / "README.md"),
                "target": str(target),
                "message": "补齐多工作项入口。",
            }
        )
    if current_version < LATEST_VERSION:
        safe_actions.append(
            {
                "action": "write_version",
                "target": str(workflow / VERSION_FILE),
                "message": f"将工作流结构版本标记为 {LATEST_VERSION}。",
            }
        )

    reviews = review_targets(project)
    return {
        "project": str(project),
        "current_version": current_version,
        "latest_version": LATEST_VERSION,
        "safe_actions": safe_actions,
        "review_actions": reviews,
        "up_to_date": current_version == LATEST_VERSION and not reviews,
    }


def apply_safe_upgrade(project: Path) -> dict[str, object]:
    plan = build_upgrade_plan(project)
    for action in plan["safe_actions"]:
        assert isinstance(action, dict)
        if action["action"] == "copy_template":
            source = Path(action["source"])
            target = Path(action["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
        elif action["action"] == "write_version":
            target = Path(action["target"])
            target.write_text(f"{LATEST_VERSION}\n", encoding="utf-8")

    created_suggestions: list[str] = []
    for review in plan["review_actions"]:
        assert isinstance(review, dict)
        suggestion = Path(review["suggestion"])
        if not suggestion.exists():
            suggestion.write_text(review["content"], encoding="utf-8")
            created_suggestions.append(str(suggestion))

    result = build_upgrade_plan(project)
    result["created_suggestions"] = created_suggestions
    return result


def format_plan(plan: dict[str, object]) -> str:
    lines = [
        f"项目：{plan['project']}",
        f"工作流结构版本：{plan['current_version']} -> {plan['latest_version']}",
    ]
    safe_actions = plan["safe_actions"]
    review_actions = plan["review_actions"]
    if safe_actions:
        lines.append("可安全执行：")
        for action in safe_actions:
            assert isinstance(action, dict)
            lines.append(f"- {action['message']} {action['target']}")
    else:
        lines.append("可安全执行：无。")
    if review_actions:
        lines.append("需要人工审阅：")
        for review in review_actions:
            assert isinstance(review, dict)
            lines.append(f"- {review['target']}，建议文件：{review['suggestion']}")
    else:
        lines.append("需要人工审阅：无。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".", help="项目控制根目录。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in [
        ("status", "查看版本和待审阅项。"),
        ("plan", "生成升级计划，不修改文件。"),
        ("apply-safe", "补齐安全结构并生成待审阅建议，不覆盖已有文档。"),
    ]:
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")

    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"项目目录不存在：{project}", file=sys.stderr)
        return 2

    try:
        if args.command == "apply-safe":
            result = apply_safe_upgrade(project)
        else:
            result = build_upgrade_plan(project)
    except ValueError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_plan(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
