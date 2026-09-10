#!/usr/bin/env python3
"""创建和检查项目工作项上下文。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


WORKFLOW_DIR = ".agent-workflow"
WORK_ITEMS_REL = Path("30-records") / "work-items"
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "assets" / "templates" / "work-item"
VALID_STATUSES = ("planned", "in_progress", "blocked", "completed", "archived")
WORK_ITEM_ID_RE = re.compile(r"^W-[A-Za-z0-9][A-Za-z0-9-]*$")
FIELD_RE = re.compile(r"^- (ID|标题|类型|状态|父工作项)：\s*(.*)$", re.MULTILINE)


def work_items_dir(project: Path) -> Path:
    return project / WORKFLOW_DIR / WORK_ITEMS_REL


def copy_template_tree(source: Path, destination: Path, replacements: dict[str, str]) -> None:
    for child in source.rglob("*"):
        relative = child.relative_to(source)
        target = destination / relative
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        content = child.read_text(encoding="utf-8")
        for old, new in replacements.items():
            content = content.replace(old, new)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def ensure_work_items_root(project: Path) -> Path:
    root = work_items_dir(project)
    if root.exists():
        return root

    workflow = project / WORKFLOW_DIR
    if not workflow.is_dir():
        raise ValueError(".agent-workflow/ 不存在，请先初始化项目工作流。")

    root.mkdir(parents=True)
    readme = TEMPLATE_ROOT.parents[0] / ".agent-workflow" / WORK_ITEMS_REL / "README.md"
    (root / "README.md").write_text(readme.read_text(encoding="utf-8"), encoding="utf-8")
    return root


def validate_work_item_id(item_id: str) -> None:
    if not WORK_ITEM_ID_RE.fullmatch(item_id):
        raise ValueError("工作项 ID 必须以 W- 开头，并且只能包含字母、数字和连字符。")


def create_work_item(project: Path, item_id: str, title: str, item_type: str, parent: str) -> Path:
    validate_work_item_id(item_id)
    if not title.strip():
        raise ValueError("工作项标题不能为空。")

    root = ensure_work_items_root(project)
    destination = root / item_id
    if destination.exists():
        raise ValueError(f"工作项已存在：{item_id}")

    copy_template_tree(
        TEMPLATE_ROOT,
        destination,
        {
            "{{WORK_ITEM_ID}}": item_id,
            "{{WORK_ITEM_TITLE}}": title.strip(),
            "{{WORK_ITEM_TYPE}}": item_type,
            "{{WORK_ITEM_PARENT}}": parent or "无",
        },
    )
    return destination


def read_work_item(path: Path) -> dict[str, str]:
    metadata = {
        "id": path.name,
        "title": "",
        "type": "",
        "status": "",
        "parent": "",
        "path": str(path),
    }
    item_file = path / "work-item.md"
    if not item_file.is_file():
        metadata["status"] = "invalid"
        return metadata

    field_names = {"ID": "id", "标题": "title", "类型": "type", "状态": "status", "父工作项": "parent"}
    for name, value in FIELD_RE.findall(item_file.read_text(encoding="utf-8", errors="replace")):
        key = field_names[name]
        if not metadata[key]:
            metadata[key] = value.strip().strip("`")
    return metadata


def list_work_items(project: Path, status: str | None = None) -> list[dict[str, str]]:
    root = work_items_dir(project)
    if not root.is_dir():
        return []

    items = [read_work_item(path) for path in root.iterdir() if path.is_dir() and path.name.startswith("W-")]
    if status:
        items = [item for item in items if item["status"] == status]
    return sorted(items, key=lambda item: item["id"])


def get_work_item(project: Path, item_id: str) -> dict[str, str]:
    validate_work_item_id(item_id)
    path = work_items_dir(project) / item_id
    if not path.is_dir():
        raise ValueError(f"工作项不存在：{item_id}")
    return read_work_item(path)


def set_status(project: Path, item_id: str, status: str) -> Path:
    if status not in VALID_STATUSES:
        allowed = "、".join(VALID_STATUSES)
        raise ValueError(f"不支持的状态：{status}。可选值：{allowed}")

    metadata = get_work_item(project, item_id)
    item_file = Path(metadata["path"]) / "work-item.md"
    content = item_file.read_text(encoding="utf-8")
    updated, count = re.subn(r"^- 状态：.*$", f"- 状态：{status}", content, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"工作项状态字段异常：{item_id}")
    item_file.write_text(updated, encoding="utf-8")
    return item_file


def format_item(item: dict[str, str]) -> str:
    return "\n".join(
        [
            f"工作项：{item['id']}",
            f"标题：{item['title'] or '待补充'}",
            f"类型：{item['type'] or '待补充'}",
            f"状态：{item['status'] or '待补充'}",
            f"路径：{item['path']}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".", help="项目控制根目录。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="创建工作项。")
    create_parser.add_argument("item_id", help="工作项 ID，例如 W-20260715-payment。")
    create_parser.add_argument("--title", required=True, help="工作项标题。")
    create_parser.add_argument("--type", default="任务", dest="item_type", help="工作项类型，例如 需求、任务或缺陷。")
    create_parser.add_argument("--parent", default="", help="父工作项 ID，可省略。")

    list_parser = subparsers.add_parser("list", help="列出工作项。")
    list_parser.add_argument("--status", choices=VALID_STATUSES, help="按状态过滤。")
    list_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")

    show_parser = subparsers.add_parser("show", help="查看工作项元数据。")
    show_parser.add_argument("item_id", help="工作项 ID。")
    show_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")

    status_parser = subparsers.add_parser("set-status", help="更新工作项生命周期状态。")
    status_parser.add_argument("item_id", help="工作项 ID。")
    status_parser.add_argument("status", choices=VALID_STATUSES, help="目标状态。")

    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"项目目录不存在：{project}", file=sys.stderr)
        return 2

    try:
        if args.command == "create":
            path = create_work_item(project, args.item_id, args.title, args.item_type, args.parent)
            print(f"已创建工作项：{path}")
        elif args.command == "list":
            items = list_work_items(project, args.status)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            elif not items:
                print("当前没有符合条件的工作项。")
            else:
                print("\n\n".join(format_item(item) for item in items))
        elif args.command == "show":
            item = get_work_item(project, args.item_id)
            if args.json:
                print(json.dumps(item, ensure_ascii=False, indent=2))
            else:
                print(format_item(item))
        elif args.command == "set-status":
            path = set_status(project, args.item_id, args.status)
            print(f"已更新工作项状态：{path}")
    except ValueError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
