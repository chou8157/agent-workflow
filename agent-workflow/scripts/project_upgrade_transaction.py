#!/usr/bin/env python3
"""项目升级的固定写集、事务日志和安全恢复。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Any

import document_baseline
import task_context
import upgrade_workflow


CONTROL_DIR = ".agent-workflow/.upgrade-transactions"
LOCK_FILE = ".agent-workflow/.upgrade-transaction.lock"
FINAL_STATES = {"committed", "recovered"}


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe(project: Path, relative: str | Path) -> Path:
    root = project.resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"事务路径越出项目目录：{relative}")
    return path


def _snapshot(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        return {"kind": "symlink", "target": str(path.readlink())}
    if not path.exists():
        return {"kind": "missing"}
    if path.is_file():
        raw = path.read_bytes()
        return {"kind": "file", "sha256": _digest(raw), "size": len(raw)}
    if path.is_dir():
        raise ValueError(f"事务写集不支持目录目标：{path}")
    raise ValueError(f"事务目标类型不受支持：{path}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".transaction-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write((json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"事务记录无法读取：{path}") from error
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("state") not in {"prepared", "running", "failed", "committed", "recovered"}:
        raise ValueError(f"事务记录无效：{path}")
    return data


@contextmanager
def project_lock(project: Path):
    path = _safe(project, LOCK_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _transactions(project: Path) -> list[tuple[Path, dict[str, Any]]]:
    root = _safe(project, CONTROL_DIR)
    if not root.exists(): return []
    if not root.is_dir() or root.is_symlink(): raise ValueError(f"事务目录无效：{root}")
    result = []
    for path in sorted(root.iterdir()):
        journal = path / "journal.json"
        if not path.is_dir() or path.is_symlink(): raise ValueError(f"事务目录包含非法条目：{path}")
        if journal.is_file(): result.append((path, _read_json(journal)))
    return result


def pending(project: Path) -> list[dict[str, Any]]:
    return [data for _path, data in _transactions(project) if data["state"] not in FINAL_STATES]


def _write_set(base_plan: dict[str, Any], document_plan: dict[str, Any]) -> list[str]:
    paths: set[str] = set()
    for action in base_plan.get("safe_actions", []): paths.add(str(Path(action["target"])))
    for action in base_plan.get("migration_actions", []): paths.add(str(Path(action["target"])))
    for action in base_plan.get("review_actions", []): paths.add(str(Path(action["suggestion"])))
    for action in document_plan.get("actions", []):
        if action.get("action") in ("initialize_baseline", "write_document"):
            paths.add(str(Path(action["target"] if action.get("action") == "initialize_baseline" else action["path"])))
    if any(action.get("action") == "write_document" for action in document_plan.get("actions", [])):
        paths.add(str(Path(document_plan["baseline"])))
    return sorted(paths)


def _relative(project: Path, absolute: str) -> str:
    return Path(absolute).resolve().relative_to(project.resolve()).as_posix()


def build_plan(project: Path, base_plan: dict[str, Any], document_plan: dict[str, Any]) -> dict[str, Any]:
    project = project.resolve()
    writes = _write_set(base_plan, document_plan)
    entries = []
    for absolute in writes:
        relative = _relative(project, absolute)
        entries.append({"path": relative, "before": _snapshot(_safe(project, relative))})
    return {"status": "blocked" if pending(project) else "ready", "control": str(_safe(project, CONTROL_DIR)), "lock": str(_safe(project, LOCK_FILE)), "write_set": entries, "pending": pending(project)}


def _restore(project: Path, journal: dict[str, Any], path: Path) -> None:
    current = _snapshot(path)
    expected = journal.get("observed_after", {}).get(str(path.relative_to(project).as_posix()))
    if expected is not None and current != expected and current != journal["before"][str(path.relative_to(project).as_posix())]:
        raise ValueError(f"事务目标在失败后被修改，拒绝覆盖：{path}")
    before = journal["before"][str(path.relative_to(project).as_posix())]
    if before["kind"] == "missing":
        if path.exists() or path.is_symlink(): path.unlink()
        return
    if before["kind"] != "file": raise ValueError(f"无法恢复事务目标：{path}")
    raw = bytes.fromhex(journal["before_bytes"][str(path.relative_to(project).as_posix())])
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".restore-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _recover_locked(project: Path) -> dict[str, Any]:
    records = [(path, data) for path, data in _transactions(project) if data["state"] not in FINAL_STATES]
    if len(records) > 1: raise ValueError("存在多个未完成项目事务，拒绝猜测恢复顺序")
    if not records: return {"status": "unchanged", "transactions": []}
    path, journal = records[0]
    for relative in journal["before"]:
        _restore(project, journal, _safe(project, relative))
    journal["state"] = "recovered"; journal["recovered_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(path / "journal.json", journal)
    return {"status": "recovered", "transactions": [{"transaction": path.name, "status": "recovered"}]}


def recover(project: Path) -> dict[str, Any]:
    project = project.resolve()
    with project_lock(project):
        return _recover_locked(project)


def apply(project: Path, base_plan: dict[str, Any], document_plan: dict[str, Any], expected_plan_fingerprint: str | None = None) -> dict[str, Any]:
    project = project.resolve()
    with project_lock(project):
        if pending(project): raise ValueError("存在未完成项目事务，请先执行 recover")
        plan = build_plan(project, base_plan, document_plan)
        if plan["status"] == "blocked": raise ValueError("存在未完成项目事务，请先执行 recover")
        transaction = uuid.uuid4().hex
        root = _safe(project, CONTROL_DIR) / transaction
        root.mkdir(parents=True, exist_ok=False)
        before = {entry["path"]: entry["before"] for entry in plan["write_set"]}
        before_bytes: dict[str, str] = {}
        for relative, snapshot in before.items():
            if snapshot["kind"] == "file": before_bytes[relative] = _safe(project, relative).read_bytes().hex()
        journal = {"schema_version": 1, "transaction": transaction, "state": "prepared", "created_at": datetime.now(timezone.utc).isoformat(), "before": before, "before_bytes": before_bytes, "observed_after": {}}
        _write_json(root / "journal.json", journal)
        try:
            journal["state"] = "running"; _write_json(root / "journal.json", journal)
            result = upgrade_workflow.apply_safe_upgrade(project, base_plan.get("plan_fingerprint"))
            document_written = document_baseline.apply_plan(project, document_plan)
            journal["observed_after"] = {relative: _snapshot(_safe(project, relative)) for relative in before}
            journal["state"] = "committed"; journal["committed_at"] = datetime.now(timezone.utc).isoformat(); _write_json(root / "journal.json", journal)
            result["transaction"] = transaction; result["document_written"] = document_written; result["transaction_status"] = "committed"
            return result
        except Exception as error:
            journal["observed_after"] = {relative: _snapshot(_safe(project, relative)) for relative in before}
            journal["state"] = "failed"; journal["error"] = str(error); _write_json(root / "journal.json", journal)
            try:
                _recover_locked(project)
            except Exception as recovery_error:
                raise ValueError(f"项目升级失败且恢复未完成，事务 {transaction}：{recovery_error}") from error
            raise
