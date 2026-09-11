#!/usr/bin/env python3
"""创建和检查项目工作项上下文。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


WORKFLOW_DIR = ".agent-workflow"
WORK_ITEMS_REL = Path("30-records") / "work-items"
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "assets" / "templates" / "work-item"
VALID_STATUSES = ("planned", "in_progress", "blocked", "completed", "archived")
ALLOWED_TRANSITIONS = {
    "planned": {"in_progress", "blocked", "archived"},
    "in_progress": {"blocked", "completed", "archived"},
    "blocked": {"in_progress", "completed", "archived"},
    "completed": {"in_progress", "archived"},
    "archived": set(),
}
STATE_FILENAME = ".state.json"
WORK_ITEM_ID_RE = re.compile(r"^W-[A-Za-z0-9][A-Za-z0-9-]*$")
FIELD_RE = re.compile(r"^- (ID|标题|类型|状态|父工作项)：\s*(.*)$", re.MULTILINE)


def work_items_dir(project: Path) -> Path:
    return project / WORKFLOW_DIR / WORK_ITEMS_REL


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def state_path(item_path: Path) -> Path:
    return item_path / STATE_FILENAME


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def validate_state(state: dict[str, object], expected_id: str | None = None) -> None:
    required = {"id", "title", "type", "status", "parent", "created_at", "updated_at"}
    missing = sorted(required - state.keys())
    if missing:
        raise ValueError(f"状态文件缺少字段：{'、'.join(missing)}")
    if expected_id and state["id"] != expected_id:
        raise ValueError(f"状态文件 ID 与目录不一致：{expected_id}")
    if state["status"] not in VALID_STATUSES:
        raise ValueError(f"状态文件包含不支持的状态：{state['status']}")
    for field in ("id", "title", "type", "updated_at"):
        if not isinstance(state[field], str) or not state[field].strip():
            raise ValueError(f"状态文件字段无效：{field}")
    for field in ("created_at", "updated_at", "completed_at"):
        value = state.get(field)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"状态文件时间字段无效：{field}")
            try:
                datetime.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"状态文件时间格式无效：{field}") from error
    if state["parent"] is not None and not isinstance(state["parent"], str):
        raise ValueError("状态文件父工作项必须是字符串或 null")
    if state["status"] == "blocked" and not state.get("blocked_reason"):
        raise ValueError("blocked 状态必须填写 blocked_reason")
    if state["status"] == "completed" and state.get("completed_at") is None and not state.get("completed_at_unknown"):
        raise ValueError("completed 状态必须填写 completed_at；历史未知时请人工裁决")
    if state["status"] != "completed" and state.get("completed_at") is not None:
        raise ValueError("非 completed 状态不应填写 completed_at")


def read_state(item_path: Path) -> dict[str, object] | None:
    path = state_path(item_path)
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"状态文件不是有效 JSON：{path}：{error}") from error
    if not isinstance(state, dict):
        raise ValueError(f"状态文件必须是 JSON 对象：{path}")
    validate_state(state, item_path.name)
    return state


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
    timestamp = now_iso()
    write_json_atomic(
        destination / STATE_FILENAME,
        {
            "id": item_id,
            "title": title.strip(),
            "type": item_type,
            "status": "planned",
            "parent": parent or None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "completed_at": None,
            "blocked_reason": None,
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
    state = read_state(path)
    if state:
        return {
            "id": str(state["id"]),
            "title": str(state["title"]),
            "type": str(state["type"]),
            "status": str(state["status"]),
            "parent": str(state["parent"] or "无"),
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


def set_status(project: Path, item_id: str, status: str, reason: str | None = None) -> Path:
    if status not in VALID_STATUSES:
        allowed = "、".join(VALID_STATUSES)
        raise ValueError(f"不支持的状态：{status}。可选值：{allowed}")

    metadata = get_work_item(project, item_id)
    item_path = Path(metadata["path"])
    state = read_state(item_path)
    if state is None:
        raise ValueError(f"工作项缺少 {STATE_FILENAME}，请先执行只读迁移检查：{item_id}")
    previous = state["status"]
    if status != previous and status not in ALLOWED_TRANSITIONS[previous]:
        raise ValueError(f"不允许的状态转换：{previous} -> {status}")
    state["status"] = status
    state["updated_at"] = now_iso()
    if status == "completed" and previous != "completed":
        state["completed_at"] = state["updated_at"]
        state["completed_at_unknown"] = False
    elif status != "completed":
        state["completed_at"] = None
        state["completed_at_unknown"] = False
    if status == "blocked":
        if not reason or not reason.strip():
            raise ValueError("设置 blocked 状态时必须提供 --reason")
        state["blocked_reason"] = reason.strip()
    else:
        state["blocked_reason"] = None
    write_json_atomic(state_path(item_path), state)
    return state_path(item_path)


def read_work_item_legacy(path: Path) -> dict[str, str]:
    item_file = path / "work-item.md"
    metadata = {"status": "", "title": "", "type": "", "parent": ""}
    if not item_file.is_file():
        return metadata
    field_names = {"标题": "title", "类型": "type", "状态": "status", "父工作项": "parent"}
    for name, value in FIELD_RE.findall(item_file.read_text(encoding="utf-8", errors="replace")):
        key = field_names.get(name)
        if key and not metadata[key]:
            metadata[key] = value.strip().strip("`")
    return metadata


def migration_report(project: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for item_path in sorted(work_items_dir(project).glob("W-*")):
        if not item_path.is_dir():
            continue
        item = read_work_item_legacy(item_path)
        if state_path(item_path).exists():
            try:
                state = read_state(item_path)
            except ValueError as error:
                findings.append({"id": item_path.name, "status": "未知", "finding": f"状态文件无效：{error}"})
                continue
            conflicts = [field for field in ("title", "type", "status") if item.get(field) and str(state[field]) != item[field]]
            if conflicts:
                findings.append({"id": item_path.name, "status": str(state["status"]), "finding": f"状态文件与旧正文冲突：{'、'.join(conflicts)}"})
            continue
        findings.append(
            {
                "id": item_path.name,
                "status": item["status"] or "未知",
                "finding": "缺少状态文件" if item["status"] in VALID_STATUSES else "缺少状态文件且旧状态无效",
            }
        )
    return findings


def migrate_legacy_items(project: Path) -> list[Path]:
    migrated: list[Path] = []
    for item_path in sorted(work_items_dir(project).glob("W-*")):
        if not item_path.is_dir() or state_path(item_path).exists():
            continue
        legacy = read_work_item_legacy(item_path)
        if legacy["status"] not in VALID_STATUSES or not legacy["title"] or not legacy["type"]:
            continue
        if legacy["status"] == "blocked":
            continue
        timestamp = now_iso()
        write_json_atomic(
            state_path(item_path),
            {
                "id": item_path.name,
                "title": legacy["title"],
                "type": legacy["type"],
                "status": legacy["status"],
                "parent": None if legacy["parent"] in ("", "无") else legacy["parent"],
                "created_at": None,
                "updated_at": timestamp,
                "completed_at": None,
                "completed_at_unknown": legacy["status"] == "completed",
                "blocked_reason": None,
                "migrated_from": "work-item.md",
                "migrated_at": timestamp,
            },
        )
        migrated.append(state_path(item_path))
    return migrated


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
    status_parser.add_argument("--reason", help="阻塞原因；设置 blocked 状态时必填。")

    migrate_parser = subparsers.add_parser("migration-check", help="检查旧工作项是否缺少状态文件。")
    migrate_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")

    apply_migrate_parser = subparsers.add_parser("migration-apply", help="为无冲突旧工作项生成状态文件。")
    apply_migrate_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")

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
            path = set_status(project, args.item_id, args.status, args.reason)
            print(f"已更新工作项状态：{path}")
        elif args.command == "migration-check":
            findings = migration_report(project)
            if args.json:
                print(json.dumps(findings, ensure_ascii=False, indent=2))
            elif not findings:
                print("未发现缺少状态文件的工作项。")
            else:
                for finding in findings:
                    print(f"{finding['id']}：{finding['finding']}，旧状态={finding['status']}")
        elif args.command == "migration-apply":
            migrated = [str(path) for path in migrate_legacy_items(project)]
            if args.json:
                print(json.dumps(migrated, ensure_ascii=False, indent=2))
            else:
                print(f"已迁移 {len(migrated)} 个无冲突工作项。")
    except ValueError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
