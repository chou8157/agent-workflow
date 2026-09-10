#!/usr/bin/env python3
"""检查 智能体工作流目录结构是否完整。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

WORKFLOW_DIR = ".agent-workflow"
REQUIRED_DIRS = [
    "00-core",
    "10-project",
    "15-modules",
    "20-gates",
    "30-records",
]
REQUIRED_FILES = [
    "README.md",
    "00-core/workflow.md",
    "00-core/principles.md",
    "00-core/disclosure.md",
    "00-core/preferences.md",
    "10-project/overview.md",
    "10-project/architecture.md",
    "10-project/conventions.md",
    "10-project/dependencies.md",
    "10-project/unknowns.md",
    "15-modules/README.md",
    "20-gates/quality-gates.md",
    "20-gates/task-gates.md",
    "20-gates/safety-gates.md",
    "30-records/current-status.md",
    "30-records/progress-log.md",
    "30-records/validation-log.md",
    "30-records/decision-log.md",
    "30-records/risk-log.md",
    "30-records/pending-fixes.md",
]
WORK_ITEMS_README = "30-records/work-items/README.md"


@dataclass
class Issue:
    code: str
    path: str
    severity: str
    message: str
    auto_fixable: bool = False


def check_project(project: Path, require_work_items: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    agents = project / "AGENTS.md"
    workflow = project / WORKFLOW_DIR

    if not agents.exists():
        issues.append(Issue("missing_agents", "AGENTS.md", "error", "AGENTS.md 不存在。"))
    else:
        text = agents.read_text(encoding="utf-8", errors="replace")
        if WORKFLOW_DIR not in text:
            issues.append(
                Issue(
                    "agents_missing_workflow_entry",
                    "AGENTS.md",
                    "warning",
                    "AGENTS.md 未提到 .agent-workflow/。",
                )
            )

    if not workflow.exists():
        issues.append(
            Issue(
                "missing_workflow_dir",
                WORKFLOW_DIR,
                "error",
                ".agent-workflow/ 不存在。",
                auto_fixable=True,
            )
        )

    for rel in REQUIRED_DIRS:
        path = workflow / rel
        if not path.is_dir():
            issues.append(
                Issue(
                    "missing_required_dir",
                    f"{WORKFLOW_DIR}/{rel}",
                    "error",
                    f"必需目录 {rel} 缺失。",
                    auto_fixable=True,
                )
            )

    for rel in REQUIRED_FILES:
        path = workflow / rel
        if not path.is_file():
            issues.append(
                Issue(
                    "missing_core_file",
                    f"{WORKFLOW_DIR}/{rel}",
                    "error",
                    f"核心工作流文件 {rel} 缺失。",
                    auto_fixable=True,
                )
            )

    if require_work_items:
        path = workflow / WORK_ITEMS_README
        if not path.is_file():
            issues.append(
                Issue(
                    "missing_work_items",
                    f"{WORKFLOW_DIR}/{WORK_ITEMS_README}",
                    "error",
                    "多工作项工作流入口缺失。",
                    auto_fixable=True,
                )
            )

    return issues



def minimal_content(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if name.endswith(".md"):
        name = name[:-3]
    title = name.replace("-", " ").title()
    return f"# {title}\n\n> 自动补齐的占位文件。请在初始化或记录模式中按项目事实补充。\n"


def fix_low_risk(project: Path, require_work_items: bool = False) -> None:
    workflow = project / WORKFLOW_DIR
    for rel in REQUIRED_DIRS:
        (workflow / rel).mkdir(parents=True, exist_ok=True)
    for rel in REQUIRED_FILES:
        path = workflow / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(minimal_content(rel), encoding="utf-8")
    if require_work_items:
        path = workflow / WORK_ITEMS_README
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(
                "# 工作项\n\n> 自动补齐的工作项入口。请使用初始化或工作项脚本补充具体规则。\n",
                encoding="utf-8",
            )


def format_text(project: Path, issues: list[Issue]) -> str:
    if not issues:
        return f"通过：{project} 已具备必需的 智能体工作流结构。"
    lines = [f"智能体工作流自检未通过：{project}"]
    for issue in issues:
        fix = " 可自动修复" if issue.auto_fixable else " 需要确认"
        lines.append(f"- [{issue.severity}] {issue.code}: {issue.path} - {issue.message} ({fix})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".", help="要检查的项目目录。")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")
    parser.add_argument("--fix-low-risk", action="store_true", help="补齐缺失的工作流目录和占位核心文件；不会修改 AGENTS.md。")
    parser.add_argument("--require-work-items", action="store_true", help="要求多工作项入口存在，用于启用多需求工作流的项目。")
    args = parser.parse_args(argv)

    project = Path(args.project).resolve()
    if not project.exists() or not project.is_dir():
        print(f"项目目录不存在：{project}", file=sys.stderr)
        return 2

    issues = check_project(project, args.require_work_items)
    if args.fix_low_risk and any(issue.auto_fixable for issue in issues):
        fix_low_risk(project, args.require_work_items)
        issues = check_project(project, args.require_work_items)

    payload = {
        "ok": not issues,
        "project": str(project),
        "issues": [asdict(issue) for issue in issues],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_text(project, issues))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
