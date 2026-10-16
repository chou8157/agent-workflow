"""P4 可选节点包装层：原文为事实权威，本地任务不依赖网络。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path

if __package__:
    from .coordinator import _read_bytes
    from .file_store import FileRegistry
    from .sqlite_store import SQLiteRegistry
    from .log_store import LogRegistry
    from .service_stores import REGISTRIES as SERVICE_REGISTRIES
else:
    from coordinator import _read_bytes
    from file_store import FileRegistry
    from sqlite_store import SQLiteRegistry
    from log_store import LogRegistry
    from service_stores import REGISTRIES as SERVICE_REGISTRIES


REPOSITORY = Path(__file__).resolve().parents[2]
PACKAGED_SCRIPT = Path(__file__).resolve().parents[1] / "task_context.py"
STABLE_SCRIPT = PACKAGED_SCRIPT if PACKAGED_SCRIPT.is_file() else REPOSITORY / "agent-workflow/scripts/task_context.py"
ITEMS = Path(".agent-workflow/30-records/work-items")
IDENTITY = ".frontier-node.json"
EXIT_BACKUP = ".frontier-exit-backup.json"
NODE_BACKUP = ".frontier-backup.json"
DOCUMENTS = (".state.json", "work-item.md", "current-status.md", "validation-log.md")
MAX_OUTPUT_BYTES = 4096
ACTIVITY_STATUSES = {"planned", "in_progress", "blocked", "completed", "archived"}
BACKENDS = {"file": FileRegistry, "sqlite": SQLiteRegistry, "log": LogRegistry}
BACKENDS.update(SERVICE_REGISTRIES)
_spec = importlib.util.spec_from_file_location("_p4_stable_tasks", STABLE_SCRIPT)
_stable = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stable)


class NodeError(ValueError):
    pass


class StaleRun(NodeError):
    pass


def registry_factory(path, backend="file"):
    if backend not in BACKENDS:
        raise NodeError("不支持的关系后端")
    return BACKENDS[backend](path)


def registry_locator(value, backend):
    return str(value) if backend in SERVICE_REGISTRIES else str(Path(value).resolve())


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def evidence_digest(raw, line_start, line_end, hash_scope="file"):
    """按原始 UTF-8 行字节校验证据；范围外的日志追加不影响 lines 引用。"""
    if hash_scope not in ("file", "lines"):
        raise NodeError("不支持的证据哈希范围")
    if (type(line_start) is not int or type(line_end) is not int or
            line_start < 1 or line_end < line_start):
        raise NodeError("证据行号范围无效")
    lines = raw.decode("utf-8").splitlines(keepends=True)
    if line_end > max(1, len(lines)):
        raise NodeError("证据行号超出文件范围")
    selected = "".join(lines[line_start - 1:line_end]).encode("utf-8")
    return digest(selected if hash_scope == "lines" else raw)


def within(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise NodeError("路径超出本次授权目录") from error
    return path


def atomic_json(path, payload):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def source_document(path, project):
    path = within(path, project)
    before = _read_bytes(path)
    content = before.decode("utf-8")
    if _read_bytes(path) != before:
        raise NodeError("原始文档在读取期间变化")
    evidence = {"path": str(path), "sha256": digest(before), "line_start": 1,
                "line_end": max(1, len(content.splitlines())), "observed_at": now()}
    return {"content": content, "source": evidence}


def identity(project):
    project = Path(project).resolve()
    if (project / NODE_BACKUP).exists():
        raise NodeError("备份不能作为活动节点执行本地任务或加入网络")
    data = json.loads(source_document(project / IDENTITY, project)["content"])
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("node_id"), str) or not data["node_id"]:
        raise NodeError("节点身份无效")
    return data


def initialize_node(project, node_id):
    project = Path(project).resolve()
    if not project.is_dir() or not (project / ".agent-workflow").is_dir():
        raise NodeError("必须先准备原工作流项目或只读来源副本")
    if not isinstance(node_id, str) or not node_id.strip():
        raise NodeError("节点身份不能为空")
    if (project / IDENTITY).exists():
        if identity(project)["node_id"] != node_id:
            raise NodeError("拒绝覆盖已有节点身份")
        return identity(project)
    data = {"schema_version": 1, "node_id": node_id, "network_enabled": False, "registry": None, "backend": "file"}
    atomic_json(project / IDENTITY, data)
    return data


def local(project, arguments):
    project = Path(project).resolve()
    if (project / NODE_BACKUP).exists():
        raise NodeError("备份不能作为活动节点执行本地任务")
    workflow = within(project / ".agent-workflow", project)
    for path in workflow.rglob("*"):
        if path.is_symlink():
            raise NodeError("本地写入包装层拒绝工作流中的符号链接")
    arguments = list(arguments)
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if not arguments:
        raise NodeError("请提供原 task_context.py 子命令")
    try:
        result = subprocess.run([sys.executable, str(STABLE_SCRIPT), str(project)] + arguments,
                                cwd=str(project), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                                capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as error:
        raise NodeError("原本地 CLI 超时；提交结果未知，请重读任务状态") from error
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
            "execution": "original_local_cli", "project": str(project)}


def field_source(document, field):
    for number, line in enumerate(document["content"].splitlines(), 1):
        if line.lstrip().startswith(json.dumps(field) + ":"):
            return dict(document["source"], line_start=number, line_end=number)
    return document["source"]


def activity_records(state, item_id, state_document):
    """读取工作项唯一的结构化业务活动记录。"""
    records = state.get("activity_records", [])
    if records is None:
        records = []
    if not isinstance(records, list):
        raise NodeError("activity_records 必须是列表")
    result, identifiers = [], set()
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise NodeError("activity_records 第 {} 项必须是对象".format(index))
        identifier = record.get("id")
        value = record.get("date")
        summary = record.get("summary")
        status = record.get("status")
        if not isinstance(identifier, str) or not identifier.strip():
            raise NodeError("activity_records 第 {} 项缺少 id".format(index))
        if identifier in identifiers:
            raise NodeError("activity_records 存在重复 id：{}".format(identifier))
        if not isinstance(value, str) or not value.strip():
            raise NodeError("activity_records 第 {} 项缺少 date".format(index))
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("必须使用 YYYY-MM-DD")
        except ValueError as error:
            raise NodeError("activity_records 第 {} 项 date 无效".format(index)) from error
        if not isinstance(summary, str) or not summary.strip():
            raise NodeError("activity_records 第 {} 项缺少 summary".format(index))
        if status not in ACTIVITY_STATUSES:
            raise NodeError("activity_records 第 {} 项 status 无效".format(index))
        evidence_refs = record.get("evidence_refs", [])
        if evidence_refs is None:
            evidence_refs = []
        if not isinstance(evidence_refs, list):
            raise NodeError("activity_records 第 {} 项 evidence_refs 必须是列表".format(index))
        normalized_refs = []
        for ref in evidence_refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                raise NodeError("activity_records 第 {} 项 evidence_refs 无效".format(index))
            ref_path = Path(ref["path"])
            if (not isinstance(ref.get("sha256"), str) or len(ref["sha256"]) != 64 or
                    ref_path.is_absolute() or ".." in ref_path.parts or
                    ref.get("hash_scope", "file") not in ("file", "lines") or
                    not all(type(ref.get(key)) is int and ref[key] >= 1
                            for key in ("line_start", "line_end")) or
                    ref["line_end"] < ref["line_start"]):
                raise NodeError("activity_records 第 {} 项 evidence_refs 行号或哈希无效".format(index))
            try:
                int(ref["sha256"], 16)
            except ValueError as error:
                raise NodeError("activity_records 第 {} 项 evidence_refs 哈希无效".format(index)) from error
            normalized_refs.append({
                "path": ref_path.as_posix(), "sha256": ref["sha256"].lower(),
                "line_start": ref["line_start"], "line_end": ref["line_end"],
            })
            if "hash_scope" in ref:
                normalized_refs[-1]["hash_scope"] = ref["hash_scope"]
        if len({ref["path"] for ref in normalized_refs}) != len(normalized_refs):
            raise NodeError("activity_records 第 {} 项 evidence_refs 存在重复路径".format(index))
        identifiers.add(identifier)
        source = dict(state_document["source"])
        result.append({
            "id": identifier,
            "date": value,
            "summary": summary,
            "status": status,
            "evidence_refs": normalized_refs,
            "source": source,
        })
    return result


def validate_activity_evidence(activities, guard):
    """确认活动引用的文件仍是写入时的同一来源。"""
    entries = guard.get("entries", {})
    for activity in activities:
        for ref in activity.get("evidence_refs", []):
            entry = entries.get(ref["path"])
            if not entry or entry.get("kind") != "file":
                raise NodeError("activity_records 证据文件不存在：{}".format(ref["path"]))
            path = within(Path(guard["project"]) / ref["path"], guard["project"])
            raw = _read_bytes(path)
            if digest(raw) != entry["sha256"]:
                raise StaleRun("活动证据在读取期间变化")
            if evidence_digest(raw, ref["line_start"], ref["line_end"], ref.get("hash_scope", "file")) != ref["sha256"]:
                raise NodeError("activity_records 证据文件哈希已变化：{}".format(ref["path"]))


def inventory(project, include_identity=True):
    """只枚举工作流内 Markdown/JSON 原文；符号链接作为缺口，不扩展读取范围。"""
    project = Path(project).resolve()
    root = within(project / ".agent-workflow", project)
    entries, sources, gaps = {}, [], []
    pending = [root]
    files = [project / IDENTITY] if include_identity else []
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            relative = str(path.relative_to(project))
            if path.is_symlink():
                entries[relative] = {"kind": "symlink", "target": os.readlink(str(path))}
                gaps.append({"path": str(path), "reason": "来源清单拒绝符号链接"})
            elif path.is_dir():
                entries[relative] = {"kind": "directory"}
                pending.append(path)
            elif path.suffix in (".md", ".json"):
                files.append(path)
    for path in sorted(files):
        relative = str(path.relative_to(project))
        try:
            document = source_document(path, project)
            entries[relative] = {"kind": "file", "sha256": document["source"]["sha256"]}
            if path.name != IDENTITY:
                sources.append(document["source"])
        except (OSError, ValueError, UnicodeError) as error:
            entries[relative] = {"kind": "unavailable", "error": str(error)}
            gaps.append({"path": str(path), "reason": str(error)})
    guard = {"project": str(project), "entries": entries}
    if not include_identity:
        guard["include_identity"] = False
    return guard, sources, gaps


def read_node(project, expected_node_id=None, standalone=False):
    project = Path(project).resolve()
    if (project / NODE_BACKUP).exists():
        raise NodeError("备份不可作为活动事实节点，请先显式恢复")
    guard, all_sources, inventory_gaps = inventory(project, include_identity=not standalone)
    config = {"node_id": expected_node_id or project.name} if standalone else identity(project)
    node_id = config["node_id"]
    if expected_node_id is not None and node_id != expected_node_id:
        raise NodeError("节点定位与权威身份不一致")
    root = within(project / ITEMS, project)
    if not root.is_dir():
        raise NodeError("工作项目录缺失，不能视为空节点")
    facts, gaps = [], list(inventory_gaps)
    for item in sorted(root.iterdir()):
        if not item.name.startswith("W-"):
            continue
        if not item.is_dir():
            gaps.append({"work_item_id": item.name, "reason": "工作项不是目录"})
            continue
        documents = {}
        for name in DOCUMENTS:
            if name == "validation-log.md" and not (item / name).exists() and not (item / name).is_symlink():
                continue
            try:
                documents[name] = source_document(item / name, project)
            except (OSError, ValueError, UnicodeError) as error:
                gaps.append({"work_item_id": item.name, "document": name, "reason": str(error)})
        state = None
        if ".state.json" in documents:
            try:
                state = json.loads(documents[".state.json"]["content"])
                if not isinstance(state, dict):
                    raise NodeError("状态不是对象")
                _stable.validate_state(state, item.name)
            except (ValueError, TypeError, KeyError) as error:
                state = None
                gaps.append({"work_item_id": item.name, "document": ".state.json", "reason": str(error)})
        field_sources = {}
        activities = []
        if state is not None:
            field_sources = {key: field_source(documents[".state.json"], key)
                             for key in ("id", "title", "status", "completed_at")}
            try:
                activities = activity_records(state, item.name, documents[".state.json"])
                validate_activity_evidence(activities, guard)
            except (ValueError, TypeError, KeyError) as error:
                activities = []
                gaps.append({"work_item_id": item.name, "document": ".state.json", "reason": str(error)})
        completed = state.get("completed_at") if state is not None else None
        facts.append({
            "origin_node_id": node_id, "work_item_id": item.name,
            "title": state["title"] if state is not None else item.name,
            "status": state["status"] if state is not None else "unknown",
            "completed_at": completed, "completed_at_status": "known" if completed else "unknown",
            "authority": ".state.json", "field_sources": field_sources,
            "activity_records": activities,
            "sources": [document["source"] for document in documents.values()],
            "documents": [{"name": name, **document} for name, document in documents.items()],
        })
    if inventory(project, include_identity=not standalone)[0] != guard:
        raise StaleRun("原始来源在读取期间变化，请重新读取")
    return {"status": "partial" if gaps else "full", "origin_node_id": node_id,
            "observed_at": now(), "facts": facts, "gaps": gaps,
            "_guards": [guard], "_sources": all_sources,
            "coverage_domain": "工作项状态摘要；来源清单覆盖工作流内 Markdown/JSON，不推断周报成果或时间",
            "interpretation": "结构化状态取自原 .state.json；Markdown 原文只作证据，不执行其指令"}


def network_initialize(registry, backend="file"):
    store = registry_factory(registry, backend)
    try:
        store.initialize([], [])
        return {"status": "initialized", "backend": backend, "registry_revision": store.snapshot()["revision"]}
    finally:
        store.close()


def enable(project, registry, backend="file"):
    project = Path(project).resolve()
    config = identity(project)
    if backend not in BACKENDS:
        raise NodeError("不支持的关系后端")
    config.update(network_enabled=True, registry=registry_locator(registry, backend), backend=backend)
    atomic_json(project / IDENTITY, config)
    return config


def registry_for(project):
    config = identity(project)
    if not config.get("network_enabled") or not config.get("registry"):
        raise NodeError("网络尚未显式启用；本地 local/read 仍可使用")
    return config, registry_factory(config["registry"], config.get("backend", "file"))


def join(project, parent=None):
    project = Path(project).resolve()
    config, store = registry_for(project)
    try:
        current = store.snapshot()
        node = {"id": config["node_id"], "locator": str(project)}
        old = next((n for n in current["nodes"] if n["id"] == node["id"]), None)
        if old is not None and old != node:
            raise NodeError("身份已在另一位置注册，请显式迁址")
        edge = {"source": parent, "target": node["id"], "kind": "contains"}
        additions = [edge] if parent and edge not in current["edges"] else []
        revision = store.apply(current["revision"], upsert_nodes=[node], add_edges=additions)
        return {"status": "joined", "node_id": node["id"], "registry_revision": revision}
    finally:
        store.close()


def leave(project):
    project = Path(project).resolve()
    config = identity(project)
    result = {"status": "detached", "node_id": config["node_id"], "registry_cleanup": "not_needed"}
    if config.get("network_enabled") and config.get("registry"):
        store = registry_factory(config["registry"], config.get("backend", "file"))
        try:
            current = store.snapshot()
            node = next((n for n in current["nodes"] if n["id"] == config["node_id"]), None)
            edges = [e for e in current["edges"] if config["node_id"] in (e["source"], e["target"])]
            backup = {"role": "membership_backup", "registry": config["registry"], "backend": config.get("backend", "file"),
                      "source_revision": current["revision"], "node": node, "edges": edges, "observed_at": now()}
            atomic_json(project / EXIT_BACKUP, backup)
            if node is not None:
                store.apply(current["revision"], remove_edges=edges, remove_nodes=[config["node_id"]])
            result["registry_cleanup"] = "complete"
        except Exception as error:
            result.update(status="partial", registry_cleanup="pending", error=str(error))
        finally:
            store.close()
    config["network_enabled"] = False
    atomic_json(project / IDENTITY, config)
    return result


def restore_membership(project):
    project = Path(project).resolve()
    config = identity(project)
    backup = json.loads(source_document(project / EXIT_BACKUP, project)["content"])
    if backup.get("role") != "membership_backup" or not backup.get("node") or backup["node"]["id"] != config["node_id"]:
        raise NodeError("退出备份不对应当前节点")
    store = registry_factory(backup["registry"], backup.get("backend", "file"))
    try:
        current = store.snapshot()
        existing = next((n for n in current["nodes"] if n["id"] == config["node_id"]), None)
        node = {"id": config["node_id"], "locator": str(project)}
        if existing is not None and existing != node:
            raise NodeError("恢复会覆盖其他活动定位，已拒绝")
        additions = [edge for edge in backup["edges"] if edge not in current["edges"]]
        revision = store.apply(current["revision"], upsert_nodes=[node], add_edges=additions)
        enable(project, backup["registry"], backup.get("backend", "file"))
        return {"status": "restored", "node_id": config["node_id"], "registry_revision": revision}
    finally:
        store.close()


def aggregate(project, source_root, denied=(), max_nodes=None, max_depth=None):
    for value, minimum in ((max_nodes, 1), (max_depth, 0)):
        if value is not None and (type(value) is not int or value < minimum):
            raise NodeError("节点或深度预算无效")
    source_root = Path(source_root).resolve()
    project = within(project, source_root)
    config, store = registry_for(project)
    try:
        current = store.snapshot()
    finally:
        store.close()
    nodes = {node["id"]: node for node in current["nodes"]}
    root_id = config["node_id"]
    if root_id not in nodes or Path(nodes[root_id]["locator"]).resolve() != project:
        raise NodeError("当前节点未加入此网络或定位不一致")
    adjacency = {node_id: [] for node_id in nodes}
    for edge in current["edges"]:
        if edge["kind"] == "contains":
            adjacency[edge["source"]].append(edge["target"])
    depths, pending = {root_id: 0}, deque([root_id])
    while pending:
        node_id = pending.popleft()
        for child in sorted(adjacency[node_id]):
            if child not in depths:
                depths[child] = depths[node_id] + 1
                pending.append(child)
    expected = sorted(depths)
    eligible = sorted((node_id for node_id in expected if max_depth is None or depths[node_id] <= max_depth),
                      key=lambda node_id: (depths[node_id], node_id))
    selected = eligible if max_nodes is None else eligible[:max_nodes]
    selected_set = set(selected)
    skipped = {node_id: "depth_budget" if max_depth is not None and depths[node_id] > max_depth else "node_budget"
               for node_id in expected if node_id not in selected_set}
    facts, succeeded, failed, gaps, guards, sources = {}, [], {}, {}, [], []
    for node_id in selected:
        try:
            if node_id in denied:
                raise NodeError("本次请求明确拒绝读取")
            path = within(nodes[node_id]["locator"], source_root)
            child_config = identity(path)
            if (not child_config.get("network_enabled") or child_config.get("registry") != config["registry"]
                    or child_config.get("backend", "file") != config.get("backend", "file")):
                raise NodeError("来源节点已退出或未授权此网络")
            result = read_node(path, node_id)
            guards.extend(result["_guards"])
            sources.extend(result["_sources"])
            for fact in result["facts"]:
                key = (fact["origin_node_id"], fact["work_item_id"])
                if key in facts:
                    raise NodeError("来源返回重复事实身份")
                facts[key] = fact
            if result["status"] != "full":
                gaps[node_id] = result["gaps"]
                raise NodeError("原始工作项文档缺失或损坏；未知字段保留 unknown")
            succeeded.append(node_id)
        except (OSError, ValueError, UnicodeError) as error:
            failed[node_id] = str(error)
    return {"status": "partial" if failed or skipped else "full", "registry_revision": current["revision"],
            "facts": [facts[key] for key in sorted(facts)], "gaps": gaps, "observed_at": now(),
            "coverage": {"expected": expected, "visited": sorted(selected),
                         "succeeded": sorted(succeeded), "failed": failed, "skipped": skipped},
            "_guards": guards, "_sources": sources, "_registry": {
                "project": str(project), "locator": config["registry"], "backend": config.get("backend", "file"),
                "revision": current["revision"]},
            "coverage_domain": "工作项状态摘要；来源清单覆盖获准节点工作流内 Markdown/JSON，不推断周报成果或时间",
            "execution": "deterministic_document_adapter_not_agent"}


def relocate(project, destination, allowed_root):
    project, destination = within(project, allowed_root), within(destination, allowed_root)
    config = identity(project)
    if destination.exists() or project == destination or project in destination.parents:
        raise NodeError("迁址目标必须不存在且不能位于源目录中")
    store, current = None, None
    if config.get("network_enabled"):
        _, store = registry_for(project)
        try:
            current = store.snapshot()
        except Exception:
            store.close()
            raise
        match = next((n for n in current["nodes"] if n["id"] == config["node_id"]), None)
        if match != {"id": config["node_id"], "locator": str(project)}:
            store.close()
            raise NodeError("原定位不一致，拒绝迁址")
    try:
        project.rename(destination)
    except Exception:
        if store is not None:
            store.close()
        raise
    try:
        if store is not None:
            store.apply(current["revision"], upsert_nodes=[{"id": config["node_id"], "locator": str(destination)}])
        return {"status": "moved", "node_id": config["node_id"], "project": str(destination)}
    except Exception as error:
        if store is not None:
            try:
                observed = store.snapshot()
            except Exception as verification_error:
                return {"status": "partial", "node_id": config["node_id"], "project": str(destination),
                        "previous_project": str(project), "registry_reconciliation_required": True,
                        "error": str(error), "verification_error": str(verification_error)}
            if any(n == {"id": config["node_id"], "locator": str(destination)} for n in observed["nodes"]):
                return {"status": "moved_commit_rechecked", "node_id": config["node_id"], "project": str(destination)}
        destination.rename(project)
        raise
    finally:
        if store is not None:
            store.close()


def backup_node(project, destination):
    project, destination = Path(project).resolve(), Path(destination).resolve()
    identity(project)
    if destination.exists() or project in destination.parents:
        raise NodeError("备份目标必须不存在且不能位于源目录中")
    for path in project.rglob("*"):
        if path.is_symlink():
            raise NodeError("备份拒绝符号链接")
    shutil.copytree(str(project), str(destination))
    files = {str(path.relative_to(project)): digest(path.read_bytes()) for path in project.rglob("*") if path.is_file()}
    atomic_json(destination / NODE_BACKUP, {"role": "node_backup", "source": str(project), "files": files, "observed_at": now()})
    if any(digest((destination / relative).read_bytes()) != expected for relative, expected in files.items()):
        raise NodeError("备份期间源发生变化，备份未验收")
    return {"status": "backup", "path": str(destination), "files": len(files)}


def reconcile_location(project, allowed_root):
    project = within(project, allowed_root)
    config, store = registry_for(project)
    try:
        current = store.snapshot()
        previous = next((node for node in current["nodes"] if node["id"] == config["node_id"]), None)
        if previous is None:
            raise NodeError("关系中没有该身份，请使用显式加入流程")
        previous_path = Path(previous["locator"]).resolve()
        if previous_path != project and previous_path.exists():
            raise NodeError("原定位仍存在，不能确认哪个副本是活动权威")
        revision = store.apply(current["revision"], upsert_nodes=[{"id": config["node_id"], "locator": str(project)}])
        return {"status": "reconciled", "node_id": config["node_id"], "project": str(project), "registry_revision": revision}
    finally:
        store.close()


def restore_node(backup, destination):
    backup, destination = Path(backup).resolve(), Path(destination).resolve()
    manifest = json.loads(source_document(backup / NODE_BACKUP, backup)["content"])
    if manifest.get("role") != "node_backup" or destination != Path(manifest["source"]) or destination.exists():
        raise NodeError("仅允许向缺失的原定位恢复，禁止产生第二个活动身份")
    actual_files = set()
    for path in backup.rglob("*"):
        if path.is_symlink():
            raise NodeError("备份中包含符号链接，拒绝恢复")
        if path.is_file() and path != backup / NODE_BACKUP:
            actual_files.add(str(path.relative_to(backup)))
    if actual_files != set(manifest["files"]):
        raise NodeError("备份文件清单不一致")
    for relative, expected in manifest["files"].items():
        path = within(backup / relative, backup)
        if digest(path.read_bytes()) != expected:
            raise NodeError("备份文件校验失败")
    shutil.copytree(str(backup), str(destination), ignore=shutil.ignore_patterns(NODE_BACKUP))
    return {"status": "restored", "project": str(destination), "node_id": identity(destination)["node_id"]}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def bounded(value, budget=MAX_OUTPUT_BYTES):
    if budget < 256 or budget > MAX_OUTPUT_BYTES:
        raise NodeError("输出预算必须介于 256 和 4096 UTF-8 字节之间（含换行）")
    if len(encoded(value)) > budget:
        raise NodeError("单条记录或响应外壳超过输出预算；未截断，请缩小证据行范围或请求字段")
    return value


def fact_metadata(fact):
    result = {key: value for key, value in fact.items() if key not in ("documents", "sources", "field_sources")}
    result["source_hashes"] = sorted(set(source["sha256"] for source in fact["sources"]))
    result["field_sources"] = {key: {field: source[field] for field in ("sha256", "line_start", "line_end")}
                               for key, source in fact["field_sources"].items()}
    return result


def gap_records(result):
    if isinstance(result["gaps"], list):
        return [dict(gap, origin_node_id=result["origin_node_id"]) for gap in result["gaps"]]
    records = []
    for node, reason in sorted(result["coverage"]["failed"].items()):
        records.append({"origin_node_id": node, "reason": reason})
    for node, reason in sorted(result["coverage"]["skipped"].items()):
        records.append({"origin_node_id": node, "reason": reason})
    for node, gaps in sorted(result["gaps"].items()):
        records.extend(dict(gap, origin_node_id=node) for gap in gaps)
    return records


def verify_run(run, source_root):
    source_root = Path(source_root).resolve()
    if str(source_root) != run["source_root"]:
        raise NodeError("本次授权来源根与运行记录不一致")
    # 派生产物不能扩大调用者授权；所有路径先校验，再读取任何来源。
    try:
        for guard in run["guards"]:
            within(guard["project"], source_root)
        for source in run["sources"]:
            within(source["path"], source_root)
        for guard in run["guards"]:
            if inventory(guard["project"], include_identity=guard.get("include_identity", True))[0] != guard:
                raise StaleRun("来源已变化，派生结果 stale；请重新执行 read/aggregate")
        if run.get("registry"):
            expected = run["registry"]
            config, store = registry_for(within(expected["project"], source_root))
            try:
                if (config["registry"] != expected["locator"] or config.get("backend", "file") != expected["backend"]
                        or store.snapshot()["revision"] != expected["revision"]):
                    raise StaleRun("关系版本或来源授权已变化，派生结果 stale")
            finally:
                store.close()
    except StaleRun:
        raise
    except Exception as error:
        raise StaleRun("来源或关系当前不可核验，派生结果 stale：" + str(error)) from error


def publish_run(result, source_root, run_root=None):
    source_root = Path(source_root).resolve()
    if run_root is None:
        run_root = Path(tempfile.gettempdir()).resolve() / "frontier-derived-runs"
    run_root = Path(run_root).resolve()
    if run_root == source_root or source_root in run_root.parents:
        raise NodeError("派生产物目录必须位于授权来源目录之外，禁止回写原文")
    run = {"schema_version": 1, "role": "derived_read_only_run", "source_root": str(source_root),
           "status": result["status"], "observed_at": result["observed_at"],
           "coverage_domain": result["coverage_domain"], "guards": result["_guards"],
           "facts": [fact_metadata(fact) for fact in result["facts"]],
           "sources": sorted(result["_sources"], key=lambda source: source["path"]),
           "gaps": gap_records(result), "registry": result.get("_registry"),
           "coverage": result.get("coverage"), "query": result.get("query")}
    verify_run(run, source_root)
    run_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="run-", dir=str(run_root))) / "run.json"
    atomic_json(destination, run)
    handle = str(destination) + "#" + digest(_read_bytes(destination))
    coverage = run["coverage"]
    summary = {key: len(value) for key, value in coverage.items()} if coverage else {
        "expected": 1, "visited": 1, "succeeded": int(run["status"] == "full"),
        "failed": int(run["status"] != "full"), "skipped": 0}
    return bounded({"status": run["status"], "role": run["role"], "handle": handle,
                    "fact_count": len(run["facts"]), "source_count": len(run["sources"]),
                    "gap_count": len(run["gaps"]), "coverage": summary,
                    "coverage_domain": run["coverage_domain"], "observed_at": run["observed_at"],
                    "registry_revision": result.get("registry_revision"), "max_output_bytes": MAX_OUTPUT_BYTES,
                    "next": "page 按 facts/sources/gaps 分页；evidence 按来源 sha256 与行号取证"})


def load_run(handle, source_root):
    try:
        path, expected = handle.rsplit("#", 1)
    except ValueError as error:
        raise NodeError("无效 handle：需要运行路径及 SHA-256") from error
    path = Path(path).absolute()
    source_root = Path(source_root).resolve()
    if path != path.resolve() or path.name != "run.json" or not path.parent.name.startswith("run-"):
        raise NodeError("handle 必须指向独立 run-* 目录内的普通 run.json，不能借符号链接改变定位")
    if source_root == path.parent or source_root in path.parents:
        raise NodeError("来源目录不能充当派生 run 控制目录")
    raw = _read_bytes(path)
    if digest(raw) != expected:
        raise NodeError("派生产物哈希不匹配；禁止把修改后的副本当作原始事实")
    run = json.loads(raw)
    if not isinstance(run, dict) or run.get("schema_version") != 1 or run.get("role") != "derived_read_only_run":
        raise NodeError("运行产物格式无效")
    verify_run(run, source_root)
    return run


def read_page(handle, source_root, kind="facts", cursor=0, budget=MAX_OUTPUT_BYTES):
    if kind not in ("facts", "sources", "gaps"):
        raise NodeError("分页类型必须是 facts/sources/gaps")
    run = load_run(handle, source_root)
    records = run[kind]
    if cursor < 0 or cursor > len(records):
        raise NodeError("分页游标越界")
    response = {"status": run["status"], "kind": kind, "cursor": cursor,
                "total": len(records), "records": [], "next_cursor": None, "done": True}
    bounded(response, budget)
    for index in range(cursor, len(records)):
        candidate = dict(response, records=response["records"] + [records[index]],
                         next_cursor=index + 1 if index + 1 < len(records) else None,
                         done=index + 1 == len(records))
        if len(encoded(candidate)) > budget:
            if not response["records"]:
                raise NodeError("单条 {} 记录超过输出预算；未截断且游标未推进".format(kind))
            break
        response = candidate
    return bounded(response, budget)


def read_evidence(handle, source_root, sha256, line_start, line_end, source_path=None, budget=MAX_OUTPUT_BYTES):
    run = load_run(handle, source_root)
    candidates = [source for source in run["sources"] if source["sha256"] == sha256
                  and (source_path is None or source["path"] == str(Path(source_path).resolve()))]
    if not candidates:
        raise NodeError("来源哈希或路径不在本次获准来源清单中")
    if len(candidates) > 1:
        raise NodeError("同哈希对应多个来源，请附加 --source-path 明确路径")
    source = candidates[0]
    document = source_document(within(source["path"], source_root), source_root)
    if document["source"]["sha256"] != sha256:
        raise StaleRun("来源已变化，证据 stale；请重新读取")
    lines = document["content"].splitlines(keepends=True)
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        raise NodeError("证据行号越界；范围必须完整有效，禁止静默截断")
    return bounded({"status": "full", "role": "source_evidence_only", "source": source,
                    "line_start": line_start, "line_end": line_end,
                    "content": "".join(lines[line_start - 1:line_end])}, budget)


class ChineseParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", help="显示中文帮助并退出")
        self._positionals.title = "命令与参数"
        self._optionals.title = "选项"

    def format_usage(self):
        return super().format_usage().replace("usage:", "用法：", 1)

    def format_help(self):
        return super().format_help().replace("usage:", "用法：", 1)

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "参数无效，请使用 --help 查看必填参数、参数类型和可选值。\n")


def main(argv=None):
    parser = ChineseParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, title="操作")
    descriptions = {"init": "初始化可选节点身份", "local": "直接运行原稳定本地 CLI，无需节点身份或网络配置",
                    "read": "读取单节点状态摘要并返回有界派生结果 handle", "enable": "显式启用关系后端",
                    "join": "加入网络", "leave": "退出网络", "restore-membership": "恢复退出前关系",
                    "aggregate": "只读聚合获准节点，返回有界计数与缺口摘要",
                    "query": "推荐模型入口：限定范围、节点、深度、耗时与响应预算", "relocate": "迁移节点目录",
                    "reconcile": "核对并修正节点定位", "backup": "备份节点并标记为非活动副本"}
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description, description=description)
        command.add_argument("--project", required=True, type=Path, help="节点项目目录")
        if name == "init": command.add_argument("--node-id", required=True, help="稳定节点身份")
        if name == "local": command.add_argument("arguments", nargs=argparse.REMAINDER, help="-- 后接原 CLI 子命令")
        if name == "enable":
            command.add_argument("--registry", required=True, help="本地权威路径或服务 p2_* namespace")
            command.add_argument("--backend", choices=sorted(BACKENDS), default="file", help="关系后端，默认 file")
        if name == "join": command.add_argument("--parent", help="可选父节点 ID")
        if name in ("aggregate", "query"):
            command.add_argument("--source-root", required=True, type=Path, help="本次允许读取的来源根")
            command.add_argument("--deny", action="append", default=[], help="明确拒绝读取的节点，可重复")
        if name in ("read", "aggregate", "query"):
            command.add_argument("--run-root", type=Path, help="派生控制目录，默认系统临时目录；必须位于来源根外")
        if name == "query":
            command.add_argument("--scope", choices=("self", "subtree"), default="subtree", help="只读自身或授权子树，默认子树")
            command.add_argument("--max-nodes", type=int, default=1000, help="最多读取节点数；未覆盖节点显式 skipped")
            command.add_argument("--max-depth", type=int, default=64, help="最短 contains 路径的最大深度，当前节点为 0")
            command.add_argument("--timeout-seconds", type=float, default=30.0, help="整个工作者的时间预算；超时终止并明确失败")
            command.add_argument("--max-bytes", type=int, default=MAX_OUTPUT_BYTES, help="响应预算，256 至 4096 UTF-8 字节")
        if name in ("relocate", "backup"): command.add_argument("--destination", required=True, type=Path, help="不存在的目标目录")
        if name in ("relocate", "reconcile"): command.add_argument("--allowed-root", required=True, type=Path, help="本次允许迁移的根目录")
    command = commands.add_parser("network-init", help="显式创建关系权威，拒绝覆盖")
    command.add_argument("--registry", required=True, help="本地路径或服务 namespace；log 后端使用目录")
    command.add_argument("--backend", choices=sorted(BACKENDS), default="file", help="关系后端，默认 file")
    command = commands.add_parser("restore-node", help="将完整备份恢复到缺失的原定位")
    command.add_argument("--backup", required=True, type=Path, help="非活动备份目录")
    command.add_argument("--destination", required=True, type=Path, help="备份记录中的原定位")
    for name in ("page", "evidence"):
        command = commands.add_parser(name, help="有界读取事实/来源/缺口元数据" if name == "page" else "按来源哈希和行号只读取证")
        command.add_argument("--handle", required=True, help="read/aggregate 返回的运行路径与 SHA-256")
        command.add_argument("--source-root", required=True, type=Path, help="重申本次授权来源根，必须与 run 一致")
        command.add_argument("--max-bytes", type=int, default=MAX_OUTPUT_BYTES, help="UTF-8 输出预算，256 至 4096 字节，含换行")
        if name == "page":
            command.add_argument("--kind", choices=("facts", "sources", "gaps"), default="facts", help="分页内容类型")
            command.add_argument("--cursor", type=int, default=0, help="上页返回的 next_cursor，首屏为 0")
        else:
            command.add_argument("--sha256", required=True, help="来源原文字节 SHA-256")
            command.add_argument("--line-start", required=True, type=int, help="起始行（从 1 开始）")
            command.add_argument("--line-end", required=True, type=int, help="结束行（包含）")
            command.add_argument("--source-path", type=Path, help="相同哈希有多个来源时指定完整路径")
    args = parser.parse_args(argv)
    try:
        if args.command == "init": result = initialize_node(args.project, args.node_id)
        elif args.command == "local": result = local(args.project, args.arguments)
        elif args.command == "read": result = publish_run(read_node(args.project), args.project, args.run_root)
        elif args.command == "network-init": result = network_initialize(args.registry, args.backend)
        elif args.command == "enable": result = enable(args.project, args.registry, args.backend)
        elif args.command == "join": result = join(args.project, args.parent)
        elif args.command == "leave": result = leave(args.project)
        elif args.command == "restore-membership": result = restore_membership(args.project)
        elif args.command == "aggregate": result = publish_run(aggregate(args.project, args.source_root, args.deny), args.source_root, args.run_root)
        elif args.command == "query":
            if __package__:
                from .bounded_node_query import query
            else:
                from bounded_node_query import query
            result = query(args.project, args.source_root, args.scope, args.max_nodes, args.max_depth,
                           args.timeout_seconds, args.max_bytes, args.deny, args.run_root)
        elif args.command == "relocate": result = relocate(args.project, args.destination, args.allowed_root)
        elif args.command == "reconcile": result = reconcile_location(args.project, args.allowed_root)
        elif args.command == "backup": result = backup_node(args.project, args.destination)
        elif args.command == "page": result = read_page(args.handle, args.source_root, args.kind, args.cursor, args.max_bytes)
        elif args.command == "evidence": result = read_evidence(args.handle, args.source_root, args.sha256, args.line_start, args.line_end, args.source_path, args.max_bytes)
        else: result = restore_node(args.backup, args.destination)
        if args.command != "local":
            bounded(result)
        sys.stdout.write(encoded(result).decode("utf-8"))
        return result.get("returncode", 2 if result.get("status") == "failed" else 0)
    except Exception as error:
        failure = {"status": "stale" if isinstance(error, StaleRun) else "failed", "error": str(error)}
        if len(encoded(failure)) > MAX_OUTPUT_BYTES:
            failure = {"status": failure["status"], "error": "错误详情超过输出预算；操作失败，未截断事实或证据"}
        sys.stdout.write(encoded(failure).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
