"""有界、只读的确定性聚合原型；不代表真实 Agent 调度。"""
import hashlib
import json
import os
import stat
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

try:
    from .storage_common import validate
except ImportError:
    from storage_common import validate


class QueryError(ValueError):
    pass


class SourceReadError(QueryError):
    def __init__(self, message, bytes_read):
        super().__init__(message)
        self.bytes_read = bytes_read


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def timestamp(value):
    if not isinstance(value, str):
        raise QueryError("时间必须为带时区字符串")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise QueryError("时间格式无效") from error
    if parsed.tzinfo is None:
        raise QueryError("时间缺少时区")
    return parsed.astimezone(timezone.utc)


def _read_bytes(path, max_bytes=None):
    if os.open not in os.supports_dir_fd:
        return _read_bytes_darwin(path) if max_bytes is None else _read_bytes_darwin(path, max_bytes)
    # 按目录描述符逐段打开，拒绝校验后被替换的符号链接以及 FIFO 等特殊文件。
    parts = Path(path).parts
    directory = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise QueryError("来源必须为普通文件")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                content = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
            if max_bytes is not None and len(content) > max_bytes:
                raise SourceReadError("来源超过单次读取预算", len(content))
            return content
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def _read_bytes_darwin(path, max_bytes=None):
    if sys.platform != "darwin":
        raise QueryError("当前运行时不支持安全来源读取，需要支持 dir_fd 的 Python")
    import fcntl

    # 旧 macOS Python 没有 openat；先核实已打开对象的真实路径，再读取内容。
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise QueryError("来源必须为普通文件")

        def check_path():
            actual = fcntl.fcntl(descriptor, getattr(fcntl, "F_GETPATH", 50), bytes(1024))
            if os.fsdecode(actual.split(b"\0", 1)[0]) != str(path):
                raise QueryError("来源路径在授权后发生变化")

        check_path()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
        if max_bytes is not None and len(content) > max_bytes:
            raise SourceReadError("来源超过单次读取预算", len(content))
        try:
            check_path()
        except (OSError, ValueError) as error:
            raise SourceReadError(str(error), len(content)) from error
        return content
    finally:
        os.close(descriptor)


def _reject_constant(value):
    raise QueryError("来源包含非标准 JSON 数值：" + value)


def _read_source(path, read_metrics):
    read_metrics["source_read_attempts"] += 1
    try:
        content = _read_bytes(path)
    except SourceReadError as error:
        read_metrics["source_bytes_read"] += error.bytes_read
        raise
    read_metrics["source_bytes_read"] += len(content)
    return content


def _read_node(node, source_root, view, read_metrics):
    path = Path(node["locator"]).resolve()
    try:
        path.relative_to(source_root)
    except ValueError as error:
        raise QueryError("来源超出授权目录") from error
    before = _read_source(path, read_metrics)
    document = json.loads(before, parse_constant=_reject_constant)
    if not isinstance(document, dict) or document.get("node_id") != node["id"]:
        raise QueryError("来源节点身份不符")
    if document.get("view_id") != view:
        raise QueryError("来源视图不符")
    records = document.get("facts")
    if not isinstance(records, list):
        raise QueryError("来源事实集合无效")
    facts = []
    source = {"path": str(path), "sha256": hashlib.sha256(before).hexdigest()}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("record_id"), str) or not record["record_id"]:
            raise QueryError("来源事实身份无效")
        if record.get("origin_node_id", node["id"]) != node["id"]:
            raise QueryError("来源事实声称其他权威节点")
        revision = record.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1 or "value" not in record:
            raise QueryError("来源事实版本或值无效")
        occurred = timestamp(record.get("occurred_at"))
        facts.append({"origin_node_id": node["id"], "record_id": record["record_id"],
                      "revision": revision, "occurred_at": occurred.isoformat(),
                      "value": record["value"], "sources": [source]})
    after = _read_source(path, read_metrics)
    if after != before:
        raise QueryError("来源在读取期间变化")
    return facts


def _scope(snapshot, root_id, scope):
    nodes = {node["id"]: node for node in snapshot["nodes"]}
    if root_id not in nodes:
        raise QueryError("查询根节点不存在")
    adjacency = {node_id: [] for node_id in nodes}
    if scope == "subtree":
        for edge in snapshot["edges"]:
            if edge["kind"] == "contains":
                adjacency[edge["source"]].append(edge["target"])
    for children in adjacency.values():
        children.sort()
    depths = {root_id: 0}
    pending = deque([root_id])
    while pending:
        node_id = pending.popleft()
        for child in adjacency[node_id]:
            if child not in depths:
                depths[child] = depths[node_id] + 1
                pending.append(child)
    return nodes, adjacency, depths


def query(snapshot, root_id, source_root, start, end, scope="subtree", strategy="central",
          max_nodes=10000, max_depth=10000, denied=None, view="main"):
    if scope not in ("self", "subtree") or strategy not in ("central", "hierarchical"):
        raise QueryError("范围或调度策略无效")
    if not isinstance(max_nodes, int) or max_nodes < 1 or not isinstance(max_depth, int) or max_depth < 0:
        raise QueryError("查询预算无效")
    start_time, end_time = timestamp(start), timestamp(end)
    if start_time >= end_time:
        raise QueryError("时间范围必须递增")
    try:
        validate(snapshot)
    except (KeyError, TypeError, ValueError) as error:
        raise QueryError("关系快照无效：" + str(error)) from error
    nodes, adjacency, depths = _scope(snapshot, root_id, scope)
    expected = sorted(depths)
    denied = set(denied or [])
    selected = sorted((node_id for node_id in expected if depths[node_id] <= max_depth),
                      key=lambda node_id: (depths[node_id], node_id))[:max_nodes]
    selected_set = set(selected)
    skipped = {node_id: "深度预算" if depths[node_id] > max_depth else "节点预算"
               for node_id in expected if node_id not in selected_set}
    if strategy == "hierarchical":
        # 迭代式逐层遍历避免 Python 递归栈限制；选择集合不依赖遍历顺序。
        pending, visited, order = [root_id], set(), []
        while pending:
            node_id = pending.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            if node_id in selected_set:
                order.append(node_id)
            pending.extend(reversed(adjacency[node_id]))
    else:
        order = selected
    source_root = Path(source_root).resolve()
    facts, conflicted, conflicts, succeeded, failed = {}, set(), [], [], {}
    keys_by_node = {node_id: set() for node_id in expected}
    read_metrics = {"source_bytes_read": 0, "source_read_attempts": 0}
    for node_id in order:
        if node_id in denied:
            failed[node_id] = "读取被拒绝"
            continue
        try:
            collected = _read_node(nodes[node_id], source_root, view, read_metrics)
        except (OSError, ValueError, TypeError, KeyError) as error:
            failed[node_id] = str(error)
            continue
        succeeded.append(node_id)
        for fact in collected:
            identity = (fact["origin_node_id"], fact["record_id"])
            if start_time <= timestamp(fact["occurred_at"]) < end_time:
                keys_by_node[node_id].add(identity)
            if identity in conflicted:
                continue
            previous = facts.get(identity)
            if previous is None:
                facts[identity] = fact
            elif encode(previous) != encode(fact):
                reason = "unresolved_version" if previous["revision"] != fact["revision"] else "conflicting_content"
                conflicts.append({"identity": list(identity), "reason": reason,
                                  "alternatives": [previous, fact]})
                del facts[identity]
                conflicted.add(identity)
    # 先完成版本和内容冲突检查，再筛选时间，避免新版本落在窗外时错误返回旧事实。
    facts = {key: fact for key, fact in facts.items()
             if start_time <= timestamp(fact["occurred_at"]) < end_time}
    if strategy == "hierarchical":
        # 自底向上合并引用集合；显式计算深层重复转发量，不把它隐藏在最终摘要中。
        pending, finished, postorder = [(root_id, False)], set(), []
        while pending:
            node_id, exiting = pending.pop()
            if exiting:
                postorder.append(node_id)
            elif node_id not in finished:
                finished.add(node_id)
                pending.append((node_id, True))
                pending.extend((child, False) for child in reversed(adjacency[node_id]))
        rollups, forwarded = {}, 0
        for node_id in postorder:
            merged = set(keys_by_node[node_id])
            for child in adjacency[node_id]:
                merged.update(rollups[child])
                forwarded += len(rollups[child])
            rollups[node_id] = merged
        output_keys = rollups[root_id] - conflicted
    else:
        output_keys = set(facts)
        forwarded = sum(len(keys) for node_id, keys in keys_by_node.items() if node_id != root_id)
    output = [facts[key] for key in sorted(output_keys)]
    return {
        "status": "partial" if failed or skipped or conflicts else "full",
        "registry_revision": snapshot["revision"], "view": view,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "facts": output, "conflicts": sorted(conflicts, key=lambda value: value["identity"]),
        "coverage": {"expected": expected, "visited": sorted(order), "succeeded": sorted(succeeded),
                     "failed": failed, "skipped": skipped},
        "metrics": dict(read_metrics, node_attempts=len(order),
                        fact_bytes=len(encode(output)), forwarded_fact_references=forwarded,
                        execution="deterministic_simulation"),
    }


def paginate(facts, max_bytes=4096):
    if max_bytes < 2:
        raise QueryError("输出预算不足")
    pages, current = [], []
    for fact in facts:
        if len(encode([fact])) > max_bytes:
            raise QueryError("单条事实超过输出预算，需下钻或调整请求")
        if current and len(encode(current + [fact])) > max_bytes:
            pages.append(current)
            current = []
        current.append(fact)
    if current:
        pages.append(current)
    return pages


def manifest(result, result_path):
    """固定字段返回给调用者；全量事实与节点覆盖表在运行产物中按需读取。"""
    coverage = result["coverage"]
    return {"status": result["status"], "registry_revision": result["registry_revision"],
            "expected_nodes": len(coverage["expected"]), "succeeded_nodes": len(coverage["succeeded"]),
            "failed_nodes": len(coverage["failed"]), "skipped_nodes": len(coverage["skipped"]),
            "fact_count": len(result["facts"]), "conflict_count": len(result["conflicts"]),
            "result_path": str(result_path), "execution": "deterministic_simulation"}
