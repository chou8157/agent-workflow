#!/usr/bin/env python3
"""项目入口文档的基线、受管理区块和三方合并辅助。"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


WORKFLOW_DIR = ".agent-workflow"
BASELINE_FILE = f"{WORKFLOW_DIR}/.document-baseline.json"
SCHEMA_VERSION = 1
SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = SKILL_ROOT / "assets" / "templates"

DOCUMENTS = (
    ("AGENTS.md", "AGENTS.md", "根入口"),
    (f"{WORKFLOW_DIR}/README.md", f"{WORKFLOW_DIR}/README.md", "工作流入口"),
    (f"{WORKFLOW_DIR}/00-core/workflow.md", f"{WORKFLOW_DIR}/00-core/workflow.md", "核心流程"),
)

MANAGED_START = re.compile(r'^<!-- agent-workflow:managed:start id="([A-Za-z0-9._-]+)" -->$')
MANAGED_END = re.compile(r'^<!-- agent-workflow:managed:end id="([A-Za-z0-9._-]+)" -->$')


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _safe_path(project: Path, relative: str) -> Path:
    path = (project / relative).resolve()
    root = project.resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"文档路径越出项目目录：{relative}")
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"文档路径不能包含符号链接：{cursor}")
    return path


def _read(path: Path) -> str:
    if path.is_symlink():
        raise ValueError(f"文档不能是符号链接：{path}")
    return path.read_text(encoding="utf-8")


def _template(relative: str) -> str:
    path = TEMPLATE_ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"文档模板不存在：{path}")
    return path.read_text(encoding="utf-8")


def managed_blocks(text: str) -> dict[str, str]:
    """提取受管理区块；不识别的旧文档不会被猜测为模板。"""
    lines = text.splitlines(keepends=True)
    blocks: dict[str, str] = {}
    index = 0
    while index < len(lines):
        start = MANAGED_START.match(lines[index].rstrip("\r\n"))
        if not start:
            index += 1
            continue
        block_id = start.group(1)
        end_index = index + 1
        while end_index < len(lines):
            end = MANAGED_END.match(lines[end_index].rstrip("\r\n"))
            if end:
                if end.group(1) != block_id:
                    raise ValueError(f"受管理区块结束标记不匹配：{block_id}")
                blocks[block_id] = "".join(lines[index + 1:end_index])
                break
            end_index += 1
        else:
            raise ValueError(f"受管理区块缺少结束标记：{block_id}")
        index = end_index + 1
    return blocks


def _entry(relative: str, template_relative: str, label: str, content: str) -> dict[str, Any]:
    raw = content.encode("utf-8")
    return {
        "template": template_relative,
        "label": label,
        "sha256": _digest(raw),
        "content": content,
        "managed_blocks": {name: _digest(value.encode("utf-8")) for name, value in managed_blocks(content).items()},
    }


def _baseline_payload(project: Path) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    for relative, template_relative, label in DOCUMENTS:
        path = _safe_path(project, relative)
        if not path.is_file():
            raise ValueError(f"缺少基线文档：{path}")
        content = _read(path)
        documents[relative] = _entry(relative, template_relative, label, content)
    return {"schema_version": SCHEMA_VERSION, "documents": documents}


def _validate_baseline(project: Path, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("documents"), dict):
        raise ValueError("文档基线格式不受支持")
    documents = data["documents"]
    result: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "documents": {}}
    for relative, template_relative, label in DOCUMENTS:
        entry = documents.get(relative)
        if not isinstance(entry, dict) or set(entry) != {"template", "label", "sha256", "content", "managed_blocks"}:
            raise ValueError(f"文档基线缺少或包含无效条目：{relative}")
        if entry["template"] != template_relative or entry["label"] != label or not isinstance(entry["content"], str):
            raise ValueError(f"文档基线来源无效：{relative}")
        if entry["sha256"] != _digest(entry["content"].encode("utf-8")):
            raise ValueError(f"文档基线摘要不匹配：{relative}")
        blocks = managed_blocks(entry["content"])
        expected_blocks = entry["managed_blocks"]
        if not isinstance(expected_blocks, dict) or expected_blocks != {name: _digest(value.encode("utf-8")) for name, value in blocks.items()}:
            raise ValueError(f"文档基线受管理区块摘要不匹配：{relative}")
        result["documents"][relative] = entry
    return result


def read_baseline(project: Path) -> dict[str, Any] | None:
    path = _safe_path(project, BASELINE_FILE)
    if not path.exists():
        return None
    try:
        data = json.loads(_read(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取文档基线：{path}") from error
    return _validate_baseline(project, data)


def _write_atomic(path: Path, raw: bytes, replace: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".document-baseline-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize_baseline(project: Path) -> str:
    """仅当当前文档与模板逐字一致时建立基线。"""
    existing = read_baseline(project)
    if existing is not None:
        return "unchanged"
    payload = _baseline_payload(project)
    for relative, template_relative, _label in DOCUMENTS:
        if payload["documents"][relative]["content"] != _template(template_relative):
            raise ValueError(f"{relative} 来源未确认，不能自动建立文档基线")
    _write_atomic(_safe_path(project, BASELINE_FILE), _canonical(payload))
    return "initialized"


def _hunks(base: list[str], other: list[str]) -> list[tuple[int, int, list[str]]]:
    matcher = difflib.SequenceMatcher(a=base, b=other, autojunk=False)
    return [(start, end, other[new_start:new_end]) for tag, start, end, new_start, new_end in matcher.get_opcodes() if tag != "equal"]


def _touches(left: tuple[int, int, list[str]], right: tuple[int, int, list[str]]) -> bool:
    left_start, left_end, _ = left
    right_start, right_end, _ = right
    if left_start == left_end and right_start == right_end:
        return left_start == right_start
    if left_start == left_end:
        return right_start <= left_start <= right_end
    if right_start == right_end:
        return left_start <= right_start <= left_end
    return left_start < right_end and right_start < left_end


def three_way_merge(base: str, current: str, target: str) -> dict[str, Any]:
    """合并旧模板、当前项目和新模板；冲突时返回可审阅正文而不写入。"""
    if current == base:
        return {"status": "updated", "content": target, "conflicts": []}
    if target == base or current == target:
        return {"status": "unchanged", "content": current, "conflicts": []}
    base_lines = base.splitlines(keepends=True)
    ours = _hunks(base_lines, current.splitlines(keepends=True))
    theirs = _hunks(base_lines, target.splitlines(keepends=True))
    output: list[str] = []
    conflicts: list[dict[str, int]] = []
    cursor = 0
    index_ours = index_theirs = 0
    while index_ours < len(ours) or index_theirs < len(theirs):
        next_ours = ours[index_ours] if index_ours < len(ours) else None
        next_theirs = theirs[index_theirs] if index_theirs < len(theirs) else None
        starts = [h[0] for h in (next_ours, next_theirs) if h is not None]
        start = min(starts)
        output.extend(base_lines[cursor:start])
        ours_group: list[tuple[int, int, list[str]]] = []
        theirs_group: list[tuple[int, int, list[str]]] = []
        if next_ours is not None and next_ours[0] == start:
            ours_group.append(next_ours)
            index_ours += 1
        if next_theirs is not None and next_theirs[0] == start:
            theirs_group.append(next_theirs)
            index_theirs += 1
        end = max([h[1] for h in ours_group + theirs_group] or [start])
        changed = True
        while changed:
            changed = False
            if index_ours < len(ours) and any(_touches(ours[index_ours], h) for h in theirs_group + ours_group):
                ours_group.append(ours[index_ours]); end = max(end, ours[index_ours][1]); index_ours += 1; changed = True
            if index_theirs < len(theirs) and any(_touches(theirs[index_theirs], h) for h in ours_group + theirs_group):
                theirs_group.append(theirs[index_theirs]); end = max(end, theirs[index_theirs][1]); index_theirs += 1; changed = True
        ours_text = base_lines[start:end] if not ours_group else sum((h[2] for h in ours_group), [])
        theirs_text = base_lines[start:end] if not theirs_group else sum((h[2] for h in theirs_group), [])
        if not ours_group:
            output.extend(theirs_text)
        elif not theirs_group:
            output.extend(ours_text)
        elif ours_text == theirs_text:
            output.extend(ours_text)
        else:
            conflicts.append({"start": start + 1, "end": end})
            output.extend(["<<<<<<< 当前项目\n", *ours_text, "=======\n", *theirs_text, ">>>>>>> 新模板\n"])
        cursor = end
    output.extend(base_lines[cursor:])
    return {"status": "conflict" if conflicts else "merged", "content": "".join(output), "conflicts": conflicts}


def build_plan(project: Path) -> dict[str, Any]:
    project = project.resolve()
    baseline_path = _safe_path(project, BASELINE_FILE)
    try:
        baseline = read_baseline(project)
    except ValueError as error:
        return {"status": "blocked", "baseline": str(baseline_path), "actions": [], "conflicts": [{"path": str(baseline_path), "finding": str(error)}], "up_to_date": False}
    if baseline is None:
        try:
            payload = _baseline_payload(project)
        except (OSError, ValueError, UnicodeError) as error:
            return {"status": "blocked", "baseline": str(baseline_path), "actions": [], "conflicts": [{"finding": str(error)}], "up_to_date": False}
        unknown = [relative for relative, template_relative, _ in DOCUMENTS if payload["documents"][relative]["content"] != _template(template_relative)]
        if unknown:
            return {"status": "review", "baseline": str(baseline_path), "actions": [], "review": [{"path": str(_safe_path(project, relative)), "finding": "未识别来源的旧文档，不能自动建立基线"} for relative in unknown], "conflicts": [], "up_to_date": False}
        return {"status": "planned", "baseline": str(baseline_path), "actions": [{"action": "initialize_baseline", "target": str(baseline_path), "message": "记录当前模板身份和受管理区块基线。"}], "conflicts": [], "up_to_date": False}

    actions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for relative, template_relative, label in DOCUMENTS:
        path = _safe_path(project, relative)
        current = _read(path)
        entry = baseline["documents"][relative]
        result = three_way_merge(entry["content"], current, _template(template_relative))
        item = {"path": str(path), "relative": relative, "label": label, "status": result["status"], "conflicts": result["conflicts"]}
        if result["status"] in ("updated", "merged") and result["content"] != current:
            item["action"] = "write_document"
            item["content"] = result["content"]
            actions.append(item)
        elif result["status"] == "conflict":
            conflicts.append({"path": str(path), "finding": "文档与新模板存在重叠修改，请审阅冲突标记", "conflicts": result["conflicts"]})
        elif result["status"] == "unchanged":
            actions.append(item)
    return {"status": "blocked" if conflicts else ("planned" if actions and any(item.get("action") for item in actions) else "unchanged"), "baseline": str(baseline_path), "actions": actions, "review": [], "conflicts": conflicts, "up_to_date": not conflicts and not any(item.get("action") for item in actions)}


def apply_plan(project: Path, plan: dict[str, Any]) -> list[str]:
    if plan.get("conflicts"):
        raise ValueError("文档计划存在冲突，未写入文档")
    written: list[str] = []
    if any(item.get("action") == "initialize_baseline" for item in plan.get("actions", [])):
        initialize_baseline(project)
        written.append(str(_safe_path(project, BASELINE_FILE)))
    for item in plan.get("actions", []):
        if item.get("action") != "write_document":
            continue
        path = _safe_path(project, item["relative"])
        _write_atomic(path, item["content"].encode("utf-8"))
        written.append(str(path))
    if any(item.get("action") == "write_document" for item in plan.get("actions", [])):
        baseline = read_baseline(project)
        if baseline is None:
            raise ValueError("文档合并缺少基线，未更新基线")
        for relative, template_relative, label in DOCUMENTS:
            content = _template(template_relative)
            baseline["documents"][relative] = _entry(relative, template_relative, label, content)
        _write_atomic(_safe_path(project, BASELINE_FILE), _canonical(baseline))
        written.append(str(_safe_path(project, BASELINE_FILE)))
    return written
