"""实验关系存储共用约束；不接入稳定版工作流。"""
from copy import deepcopy


class RevisionConflict(ValueError):
    pass


def normalize(snapshot):
    value = deepcopy(snapshot)
    value["nodes"] = sorted(value["nodes"], key=lambda node: node["id"])
    value["edges"] = sorted(value["edges"], key=lambda edge: (edge["source"], edge["target"], edge["kind"]))
    return value


def validate(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("关系快照必须为对象")
    if type(snapshot.get("revision")) is not int or snapshot["revision"] < 1:
        raise ValueError("关系版本无效")
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("节点和边必须为列表")
    ids = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            raise ValueError("节点身份无效")
        if not isinstance(node.get("locator"), str) or not node["locator"] or node["id"] in ids:
            raise ValueError("节点定位无效或身份重复")
        ids.add(node["id"])
    adjacency = {node_id: [] for node_id in ids}
    indegree = {node_id: 0 for node_id in ids}
    seen = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("关系格式无效")
        source, target, kind = edge.get("source"), edge.get("target"), edge.get("kind")
        if source not in ids or target not in ids or kind not in ("contains", "related"):
            raise ValueError("关系存在悬空引用或未知类型")
        identity = (source, target, kind)
        if identity in seen:
            raise ValueError("关系重复")
        seen.add(identity)
        if kind == "contains":
            adjacency[source].append(target)
            indegree[target] += 1
    queue = [node_id for node_id, count in indegree.items() if count == 0]
    consumed = 0
    while queue:
        node_id = queue.pop()
        consumed += 1
        for target in adjacency[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if consumed != len(ids):
        raise ValueError("包含关系成环")


def mutated(snapshot, expected_revision, upsert_nodes=None, add_edges=None, remove_edges=None, remove_nodes=None):
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError("预期关系版本无效")
    if snapshot["revision"] != expected_revision:
        raise RevisionConflict("关系版本已变化，请重新读取后重试")
    nodes = {node["id"]: deepcopy(node) for node in snapshot["nodes"]}
    for node_id in remove_nodes or []:
        if node_id not in nodes:
            raise ValueError("待删除节点不存在")
        del nodes[node_id]
    for node in upsert_nodes or []:
        nodes[node["id"]] = deepcopy(node)
    removed = {(edge["source"], edge["target"], edge["kind"]) for edge in remove_edges or []}
    edges = [deepcopy(edge) for edge in snapshot["edges"] if (edge["source"], edge["target"], edge["kind"]) not in removed]
    edges.extend(deepcopy(add_edges or []))
    value = {"revision": snapshot["revision"] + 1, "nodes": list(nodes.values()), "edges": edges}
    validate(value)
    return normalize(value)
