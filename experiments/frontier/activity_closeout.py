"""实验用活动收口：向单个工作项幂等追加一条结构化活动事实。

该模块只用于实验副本。它不迁移历史日志，也不更新父节点或关系库。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

if __package__:
    from . import node_workflow
    from .coordinator import _read_bytes
else:
    import node_workflow
    from coordinator import _read_bytes


ACTIVITY_STATUSES = node_workflow.ACTIVITY_STATUSES


class CloseoutError(ValueError):
    """收口输入或目标状态不满足实验契约。"""


def _now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _load_state(item_path):
    state_path = item_path / ".state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise CloseoutError("工作项缺少可写的 .state.json")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CloseoutError(".state.json 无法读取或不是有效 JSON") from error
    if not isinstance(state, dict):
        raise CloseoutError(".state.json 必须是对象")
    try:
        node_workflow._stable.validate_state(state, item_path.name)
    except (ValueError, TypeError, KeyError) as error:
        raise CloseoutError(".state.json 未通过现有工作项状态校验：{}".format(error)) from error
    return state


def _evidence(project, ref):
    if not isinstance(ref, dict):
        raise CloseoutError("evidence_refs 每项必须是对象")
    relative = ref.get("path")
    expected_hash = ref.get("sha256")
    line_start, line_end = ref.get("line_start"), ref.get("line_end")
    hash_scope = ref.get("hash_scope", "file")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise CloseoutError("证据路径必须是项目内相对路径")
    relative_path = Path(relative)
    if not relative_path.parts or ".." in relative_path.parts:
        raise CloseoutError("证据路径不能包含 ..")
    if relative_path.parts[0] != ".agent-workflow" or relative_path.suffix not in (".md", ".json"):
        raise CloseoutError("证据必须是 .agent-workflow 内的 Markdown 或 JSON 文件")
    if relative_path.name == ".state.json":
        raise CloseoutError("证据不能引用 .state.json，请引用独立验证记录，避免状态写入使自身证据失效")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise CloseoutError("证据必须提供 SHA-256")
    try:
        int(expected_hash, 16)
    except ValueError as error:
        raise CloseoutError("证据 SHA-256 格式无效") from error
    if (type(line_start) is not int or type(line_end) is not int or
            line_start < 1 or line_end < line_start):
        raise CloseoutError("证据行号范围无效")
    candidate = project / relative_path
    if any(part.is_symlink() for part in (candidate,) + tuple(candidate.parents) if part != project):
        raise CloseoutError("证据路径不能包含符号链接")
    path = candidate.resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError as error:
        raise CloseoutError("证据路径超出项目目录") from error
    try:
        if path.is_symlink() or not path.is_file():
            raise CloseoutError("证据文件不存在或不是普通文件")
        raw = _read_bytes(path)
        actual_hash = node_workflow.evidence_digest(raw, line_start, line_end, hash_scope)
    except CloseoutError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise CloseoutError("证据文件无法安全读取") from error
    if actual_hash != expected_hash.lower():
        raise CloseoutError("证据文件哈希已变化")
    normalized = {
        "path": relative_path.as_posix(),
        "sha256": expected_hash.lower(),
        "line_start": line_start,
        "line_end": line_end,
    }
    if "hash_scope" in ref:
        normalized["hash_scope"] = hash_scope
    return normalized


def _record(project, payload):
    if not isinstance(payload, dict):
        raise CloseoutError("活动记录必须是对象")
    identifier = payload.get("id")
    value = payload.get("date")
    summary = payload.get("summary")
    status = payload.get("status")
    if not isinstance(identifier, str) or not identifier.strip():
        raise CloseoutError("活动记录缺少 id")
    if not isinstance(value, str):
        raise CloseoutError("活动记录缺少 date")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("必须使用 YYYY-MM-DD")
    except ValueError as error:
        raise CloseoutError("活动记录 date 无效") from error
    if not isinstance(summary, str) or not summary.strip():
        raise CloseoutError("活动记录缺少 summary")
    if status not in ACTIVITY_STATUSES:
        raise CloseoutError("活动记录 status 无效")
    refs = payload.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        raise CloseoutError("每次收口至少需要一条 evidence_refs")
    normalized = [_evidence(project, ref) for ref in refs]
    unique_paths = [ref["path"] for ref in normalized]
    if len(unique_paths) != len(set(unique_paths)):
        raise CloseoutError("evidence_refs 不能重复引用同一文件")
    return {
        "id": identifier.strip(),
        "date": value,
        "summary": summary.strip(),
        "status": status,
        "evidence_refs": normalized,
    }


def _canonical(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def append_activity(project, item_id, payload, lock_timeout=5.0):
    """追加活动事实；相同 ID 和内容重复提交时不写文件。"""
    project = Path(project).resolve()
    try:
        node_workflow._stable.validate_work_item_id(item_id)
    except ValueError as error:
        raise CloseoutError("工作项 ID 无效") from error
    item = project / node_workflow.ITEMS / item_id
    if not item.is_dir() or item.is_symlink():
        raise CloseoutError("工作项目录不存在或不是普通目录")
    if any(part.is_symlink() for part in item.parents if part != project):
        raise CloseoutError("工作项路径不能包含符号链接")
    with node_workflow._stable.state_lock(item / ".state.json", timeout=lock_timeout):
        return _append_locked(project, item_id, item, payload)


def _append_locked(project, item_id, item, payload):
    state = _load_state(item)
    try:
        node_workflow.activity_records(state, item_id, {"source": {"path": str(item / ".state.json"),
                                                          "sha256": "0" * 64, "line_start": 1, "line_end": 1}})
    except (ValueError, TypeError, KeyError) as error:
        raise CloseoutError("现有 activity_records 无效：{}".format(error)) from error
    record = _record(project, payload)
    records = state.get("activity_records", [])
    if records is None:
        records = []
    if not isinstance(records, list):
        raise CloseoutError("现有 activity_records 不是列表")
    for existing in records:
        if not isinstance(existing, dict):
            raise CloseoutError("现有 activity_records 包含非法项")
        if existing.get("id") != record["id"]:
            continue
        if _canonical(existing) != _canonical(record):
            raise CloseoutError("相同活动 ID 已存在不同内容，拒绝覆盖")
        return {"status": "unchanged", "record": existing, "state_sha256": _digest(_read_bytes(item / ".state.json"))}
    updated = dict(state)
    updated["activity_records"] = records + [record]
    updated["updated_at"] = _now()
    node_workflow._stable.write_json_atomic(item / ".state.json", updated)
    raw = _read_bytes(item / ".state.json")
    return {"status": "created", "record": record, "state_sha256": _digest(raw)}


def evidence_ref(project, relative, line_start=1, line_end=None, hash_scope="file"):
    """根据当前文件内容生成待传给 append_activity 的证据引用。"""
    project = Path(project).resolve()
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts or not relative_path.parts:
        raise CloseoutError("证据路径必须是项目内相对路径")
    path = project / relative_path
    if any(part.is_symlink() for part in (path,) + tuple(path.parents) if part != project):
        raise CloseoutError("证据路径不能包含符号链接")
    node_workflow.within(path, project)
    raw = _read_bytes(path)
    if line_end is None:
        line_end = max(1, len(raw.decode("utf-8").splitlines()))
    ref = {"path": relative_path.as_posix(),
           "sha256": node_workflow.evidence_digest(raw, line_start, line_end, hash_scope),
           "line_start": line_start, "line_end": line_end}
    if hash_scope != "file":
        ref["hash_scope"] = hash_scope
    return _evidence(project, ref)
