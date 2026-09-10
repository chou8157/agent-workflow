#!/usr/bin/env python3
"""从内置模板生成 智能体工作流文件。"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = SKILL_ROOT / "assets" / "templates"
WORKFLOW_DIR = ".agent-workflow"
SHARED_DIR = ".agent-workflow-shared"


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


def scaffold_project(project: Path, overwrite: bool = False) -> tuple[list[str], list[str]]:
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

    written += copy_missing(TEMPLATE_ROOT / WORKFLOW_DIR, project / WORKFLOW_DIR, overwrite=overwrite)
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
    args = parser.parse_args(argv)

    project = Path(args.project).resolve()
    if args.shared:
        written, warnings = scaffold_shared(project, args.shared_name, args.overwrite)
    else:
        written, warnings = scaffold_project(project, args.overwrite)

    for path in written:
        print(f"已创建：{path}")
    for warning in warnings:
        print(f"警告：{warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
