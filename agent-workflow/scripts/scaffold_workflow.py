#!/usr/bin/env python3
"""从内置模板生成 智能体工作流文件。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = SKILL_ROOT / "assets" / "templates"
WORKFLOW_DIR = ".agent-workflow"
SHARED_DIR = ".agent-workflow-shared"
CAPABILITIES_FILE = ".capabilities.json"
PROFILE_CAPABILITIES = {
    "minimum": ["core", "work-items"],
    "standard": ["core", "work-items", "decisions", "knowledge", "evidence", "delivery"],
    "advanced": ["core", "work-items", "decisions", "contracts", "knowledge", "evidence", "delivery", "audit", "shared-workflow"],
}
CAPABILITY_DEPENDS = {
    "core": [], "work-items": ["core"], "decisions": ["core"], "contracts": ["core"],
    "knowledge": ["core"], "evidence": ["core"], "delivery": ["evidence"],
    "audit": ["evidence", "decisions"], "shared-workflow": ["core"],
}
CAPABILITY_PATHS = {
    "core": ["README.md", "WORKFLOW_VERSION", "00-core", "30-records/current-status.md"],
    "work-items": ["30-records/work-items"],
    "decisions": ["30-records/decision-log.md"],
    "knowledge": ["10-project/overview.md", "10-project/unknowns.md"],
    "contracts": ["10-project/architecture.md", "10-project/dependencies.md"],
    "evidence": ["30-records/validation-log.md", "30-records/risk-log.md"],
    "delivery": ["30-records/delivery"],
    "audit": ["20-gates"],
    "shared-workflow": [],
}


def copy_missing(src: Path, dst: Path, overwrite: bool = False) -> list[str]:
    written: list[str] = []
    if src.is_dir():
        for child in src.rglob("*"):
            rel = child.relative_to(src)
            target = dst / rel
            if child.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not overwrite:
                continue
            shutil.copy2(child, target)
            written.append(str(target))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if overwrite or not dst.exists():
            shutil.copy2(src, dst)
            written.append(str(dst))
    return written


def scaffold_project(project: Path, overwrite: bool = False, profile: str = "minimum", capabilities: list[str] | None = None) -> tuple[list[str], list[str]]:
    written: list[str] = []
    warnings: list[str] = []
    project.mkdir(parents=True, exist_ok=True)

    agents_src = TEMPLATE_ROOT / "AGENTS.md"
    agents_dst = project / "AGENTS.md"
    if agents_dst.exists():
        text = agents_dst.read_text(encoding="utf-8", errors="replace")
        if WORKFLOW_DIR not in text:
            suggestion = project / "AGENTS.md.agent-workflow-suggestion"
            suggestion.write_text(
                "\n## 智能体工作流入口\n\n- 请阅读 `.agent-workflow/README.md`。\n- 项目状态见 `.agent-workflow/30-records/current-status.md`。\n- 需求或任务状态见 `.agent-workflow/30-records/work-items/`。\n",
                encoding="utf-8",
            )
            warnings.append("已有 AGENTS.md 缺少工作流入口；已生成 AGENTS.md.agent-workflow-suggestion 供确认。")
    else:
        written += copy_missing(agents_src, agents_dst, overwrite=overwrite)

    if profile not in PROFILE_CAPABILITIES:
        raise ValueError(f"未知 profile：{profile}")
    requested = list(capabilities or PROFILE_CAPABILITIES[profile])
    enabled: list[str] = []
    def add_capability(name: str) -> None:
        if name not in CAPABILITY_PATHS:
            raise ValueError(f"未知能力：{name}")
        for dependency in CAPABILITY_DEPENDS[name]:
            add_capability(dependency)
        if name not in enabled:
            enabled.append(name)
    for name in requested:
        add_capability(name)
    workflow_dst = project / WORKFLOW_DIR
    for capability in enabled:
        for rel in CAPABILITY_PATHS[capability]:
            written += copy_missing(TEMPLATE_ROOT / WORKFLOW_DIR / rel, workflow_dst / rel, overwrite=overwrite)
    manifest = workflow_dst / CAPABILITIES_FILE
    if not manifest.exists() or overwrite:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"profile": profile, "enabled": enabled}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(str(manifest))
    return written, warnings


def scaffold_shared(project: Path, name: str = SHARED_DIR, overwrite: bool = False) -> tuple[list[str], list[str]]:
    project.mkdir(parents=True, exist_ok=True)
    written = copy_missing(TEMPLATE_ROOT / SHARED_DIR, project / name, overwrite=overwrite)
    return written, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".", help="目标项目目录。")
    parser.add_argument("--shared", action="store_true", help="生成多项目共享工作流目录。")
    parser.add_argument("--shared-name", default=SHARED_DIR, help="共享工作流目录名称。")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有模板文件，请谨慎使用。")
    parser.add_argument("--profile", choices=sorted(PROFILE_CAPABILITIES), default="minimum", help="初始化能力组合，默认 minimum。")
    parser.add_argument("--capability", action="append", dest="capabilities", help="额外启用能力，可重复指定。")
    args = parser.parse_args(argv)

    project = Path(args.project).resolve()
    if args.shared:
        written, warnings = scaffold_shared(project, args.shared_name, args.overwrite)
    else:
        written, warnings = scaffold_project(project, args.overwrite, args.profile, args.capabilities)

    for path in written:
        print(f"已创建：{path}")
    for warning in warnings:
        print(f"警告：{warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
