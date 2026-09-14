#!/usr/bin/env python3
"""检查 智能体工作流目录结构是否完整。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import re
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
CAPABILITIES_FILE = ".capabilities.json"
CAPABILITY_REQUIRED = {
    "core": ["README.md", "WORKFLOW_VERSION", "00-core/workflow.md", "00-core/principles.md", "00-core/disclosure.md", "00-core/preferences.md", "30-records/current-status.md"],
    "work-items": ["30-records/work-items/README.md"],
    "decisions": ["30-records/decision-log.md"],
    "knowledge": ["10-project/overview.md", "10-project/unknowns.md"],
    "contracts": ["10-project/architecture.md", "10-project/dependencies.md"],
    "evidence": ["30-records/validation-log.md", "30-records/risk-log.md"],
    "delivery": ["30-records/delivery"],
    "audit": ["20-gates"],
}
WORK_ITEMS_README = "30-records/work-items/README.md"
STATE_FILENAME = ".state.json"
DELIVERY_DIR = "30-records/delivery"
PROJECT_STATE_FIELDS = ("project_status", "current_phase", "primary_work_item", "updated_at")
INTERNAL_WORK_ITEM = re.compile(r"\bW-[A-Za-z0-9][A-Za-z0-9_-]*\b")


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

    enabled = None
    manifest = workflow / CAPABILITIES_FILE
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            enabled = data.get("enabled")
            if not isinstance(enabled, list) or any(item not in CAPABILITY_REQUIRED for item in enabled):
                raise ValueError("enabled 必须是已知能力列表")
        except (OSError, json.JSONDecodeError, ValueError) as error:
            issues.append(Issue("invalid_capabilities", str(manifest.relative_to(project)), "error", f"能力清单无效：{error}"))
            enabled = None

    required_dirs = REQUIRED_DIRS if enabled is None else [rel for cap in enabled for rel in ("00-core", "30-records") if cap == "core"]
    if enabled is not None:
        required_dirs = []
        if "core" in enabled: required_dirs += ["00-core", "30-records"]
        if "audit" in enabled: required_dirs += ["20-gates"]
    for rel in dict.fromkeys(required_dirs):
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

    required_files = REQUIRED_FILES if enabled is None else [item for cap in enabled for item in CAPABILITY_REQUIRED[cap] if not (workflow / item).is_dir()]
    for rel in dict.fromkeys(required_files):
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

    work_items_root = workflow / "30-records" / "work-items"
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
        if path.is_file():
            for item_path in sorted(work_items_root.glob("W-*")):
                if item_path.is_dir() and not (item_path / STATE_FILENAME).is_file():
                    issues.append(
                        Issue(
                            "missing_work_item_state",
                            str(item_path.relative_to(project)),
                            "warning",
                            "工作项缺少 .state.json，请先执行 task_context.py migration-check。",
                        )
                    )
            current_status = workflow / "30-records" / "current-status.md"
            if current_status.is_file():
                text = current_status.read_text(encoding="utf-8", errors="replace")
                block = re.search(r"```yaml\s*(.*?)\s*```", text, re.DOTALL)
                if not block:
                    issues.append(Issue("missing_project_state", str(current_status.relative_to(project)), "warning", "项目状态缺少结构化 YAML 区块。"))
                else:
                    values = dict(re.findall(r"^([a-z_]+):\s*(.*?)\s*$", block.group(1), re.MULTILINE))
                    missing = [field for field in PROJECT_STATE_FIELDS if field not in values]
                    if missing:
                        issues.append(Issue("invalid_project_state", str(current_status.relative_to(project)), "warning", f"项目状态缺少字段：{'、'.join(missing)}。"))
                    primary = values.get("primary_work_item", "").strip(" `")
                    if primary and primary not in {path.name for path in (workflow / "30-records" / "work-items").glob("W-*") if path.is_dir()} and primary not in ("null", "待补充"):
                        issues.append(Issue("unknown_primary_work_item", str(current_status.relative_to(project)), "warning", f"项目主工作项不存在：{primary}。"))

    if work_items_root.is_dir():
        for item_path in sorted(work_items_root.glob("W-*")):
            if not item_path.is_dir() or not (item_path / STATE_FILENAME).is_file():
                continue
            state_file = item_path / STATE_FILENAME
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    raise ValueError("必须是 JSON 对象")
                required = {"id", "title", "type", "status", "parent", "created_at", "updated_at"}
                missing = sorted(required - state.keys())
                if missing:
                    raise ValueError(f"缺少字段：{'、'.join(missing)}")
                if state["id"] != item_path.name or state["status"] not in ("planned", "in_progress", "blocked", "completed", "archived"):
                    raise ValueError("ID 或状态值无效")
                if state["status"] == "blocked" and not state.get("blocked_reason"):
                    raise ValueError("blocked 缺少 blocked_reason")
                if state["status"] == "completed" and not state.get("completed_at") and not state.get("completed_at_unknown"):
                    raise ValueError("completed 缺少 completed_at")
                if state["status"] != "completed" and state.get("completed_at") is not None:
                    raise ValueError("非 completed 不应有 completed_at")
            except (OSError, json.JSONDecodeError, ValueError) as error:
                issues.append(Issue("invalid_work_item_state", str(state_file.relative_to(project)), "error", f"状态文件无效：{error}"))

    delivery_root = workflow / DELIVERY_DIR
    published_root = delivery_root / "published"
    if published_root.is_dir():
        for artifact in sorted(published_root.glob("*.md")):
            if artifact.name == "README.md":
                continue
            metadata_file = artifact.with_suffix(".json")
            try:
                if not metadata_file.is_file():
                    raise ValueError("缺少旁置元数据")
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                required = {"artifact_id", "artifact_type", "audience", "period", "version", "status", "content_sha256"}
                missing = sorted(required - metadata.keys())
                if missing:
                    raise ValueError(f"缺少字段：{'、'.join(missing)}")
                if metadata["status"] not in ("published", "superseded", "withdrawn"):
                    raise ValueError("发布物状态必须是 published、superseded 或 withdrawn")
                if metadata["status"] == "superseded":
                    replacement = str(metadata.get("superseded_by", "")).strip()
                    if not replacement:
                        raise ValueError("superseded 交付物缺少 superseded_by")
                    if not (published_root / f"{replacement}.md").is_file():
                        raise ValueError(f"替代交付物不存在：{replacement}")
                content = artifact.read_text(encoding="utf-8", errors="replace")
                expected_hash = metadata.get("content_sha256")
                actual_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
                if expected_hash != actual_hash:
                    raise ValueError("正文内容哈希不匹配")
                if any(marker in content for marker in (".agent-workflow/", "待确认", "未验证")) or INTERNAL_WORK_ITEM.search(content):
                    raise ValueError("正文包含内部路径或未确认判断")
            except (OSError, json.JSONDecodeError, ValueError) as error:
                issues.append(Issue("invalid_delivery_artifact", str(artifact.relative_to(project)), "error", f"交付物无效：{error}"))

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
