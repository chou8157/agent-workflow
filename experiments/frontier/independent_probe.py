"""独立拓扑 oracle 与来源边界探针；不表示真实 Agent、网络或性能验收。"""

import argparse
import hashlib
import json
import platform
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from . import coordinator
else:
    import coordinator


ROOT = Path(__file__).resolve().parent
START, END = "2026-10-05T00:00:00+00:00", "2026-10-12T00:00:00+00:00"
WHEN = "2026-10-07T00:00:00+00:00"


def fingerprints():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("coordinator.py", "storage_common.py", "independent_probe.py")}


def topology_probes(seed, cases, node_count, deep_count):
    rng = random.Random(seed)
    actual_reads, samples = [], []
    original = coordinator._read_node

    def synthetic(node, source_root, view, read_metrics):
        actual_reads.append(node["id"])
        return [{"origin_node_id": node["id"], "record_id": "x", "revision": 1,
                 "occurred_at": WHEN, "value": node["id"], "sources": []}]

    coordinator._read_node = synthetic
    try:
        for case in range(cases):
            ids = ["n{:02d}".format(index) for index in range(node_count)]
            rng.shuffle(ids)
            edges = [(i, j) for i in range(node_count) for j in range(i + 1, node_count)
                     if rng.random() < 0.24]
            # 用全对最短路计算 oracle，不复用被测的 BFS 或后序归并。
            unreachable = node_count + 1
            distances = [[0 if i == j else unreachable for j in range(node_count)]
                         for i in range(node_count)]
            for i, j in edges:
                distances[i][j] = 1
            for k in range(node_count):
                for i in range(node_count):
                    for j in range(node_count):
                        distances[i][j] = min(distances[i][j], distances[i][k] + distances[k][j])
            max_nodes, max_depth = rng.randrange(1, node_count + 1), rng.randrange(0, 8)
            denied = set(rng.sample(ids, min(2, node_count)))
            reachable = [i for i in range(node_count) if distances[0][i] < unreachable]
            selected = sorted((i for i in reachable if distances[0][i] <= max_depth),
                              key=lambda i: (distances[0][i], ids[i]))[:max_nodes]
            wanted = {ids[i] for i in selected} - denied
            state = {"revision": 1, "nodes": [{"id": node, "locator": "synthetic"} for node in ids],
                     "edges": [{"source": ids[i], "target": ids[j], "kind": "contains"} for i, j in edges]}
            query_input = {"snapshot": state, "root": ids[0], "max_nodes": max_nodes,
                           "max_depth": max_depth, "denied": sorted(denied)}
            sample = {"case": case, "input_sha256": hashlib.sha256(coordinator.encode(query_input)).hexdigest(),
                      "edges": len(edges), "expected_facts": len(wanted), "strategies": {}}
            for strategy in ("central", "hierarchical"):
                actual_reads[:] = []
                result = coordinator.query(state, ids[0], "/private/tmp", START, END, strategy=strategy,
                                           max_nodes=max_nodes, max_depth=max_depth, denied=denied)
                assert {fact["origin_node_id"] for fact in result["facts"]} == wanted, (case, strategy)
                assert all(fact["value"] == fact["origin_node_id"] for fact in result["facts"])
                assert len(actual_reads) == len(set(actual_reads)) == len(wanted)
                assert set(result["coverage"]["expected"]) == {ids[i] for i in reachable}
                assert set(result["coverage"]["visited"]) == {ids[i] for i in selected}
                expected_status = "full" if len(wanted) == len(reachable) else "partial"
                assert result["status"] == expected_status
                sample["strategies"][strategy] = {"passed": True, "status": result["status"],
                                                     "fact_count": len(result["facts"])}
            samples.append(sample)
        state = {"revision": 1, "nodes": [{"id": str(i), "locator": "synthetic"} for i in range(deep_count)],
                 "edges": [{"source": str(i), "target": str(i + 1), "kind": "contains"}
                           for i in range(deep_count - 1)]}
        result = coordinator.query(state, "0", "/private/tmp", START, END, strategy="hierarchical",
                                   max_nodes=deep_count, max_depth=deep_count)
        assert result["status"] == "full" and len(result["facts"]) == deep_count
        assert result["metrics"]["forwarded_fact_references"] == deep_count * (deep_count - 1) // 2
        deep = {"nodes": deep_count, "passed": True, "status": result["status"],
                "forwarded_fact_references": result["metrics"]["forwarded_fact_references"]}
        return {"random_dag_cases": samples, "deep_chain": deep}
    finally:
        coordinator._read_node = original


def boundary_probes():
    outcomes = []
    for strategy in ("central", "hierarchical"):
        for case in ("cross_window_conflict", "json_boolean_number_conflict", "foreign_origin",
                     "source_change", "read_bytes", "file_symlink_race", "directory_symlink_race"):
            with tempfile.TemporaryDirectory(prefix="frontier-independent-probe-", dir="/private/tmp") as temporary:
                base = Path(temporary)
                source_root = base / "sources"
                parent = source_root / "sub"
                parent.mkdir(parents=True)
                path = parent / "A.json"
                record = {"record_id": "x", "revision": 1, "occurred_at": WHEN, "value": "inside"}
                records = [dict(record)]
                if case == "cross_window_conflict":
                    records.append(dict(record, revision=2, occurred_at="2026-10-20T00:00:00+00:00", value="new"))
                elif case == "json_boolean_number_conflict":
                    records = [dict(record, value=True), dict(record, value=1)]
                elif case == "foreign_origin":
                    records[0]["origin_node_id"] = "B"
                document = {"node_id": "A", "view_id": "main", "facts": records}
                path.write_bytes(coordinator.encode(document))
                outside = base / "outside"
                outside.mkdir()
                outside_file = outside / "A.json"
                outside_file.write_bytes(coordinator.encode(dict(document, facts=[dict(record, value="outside")])))
                state = {"revision": 1, "nodes": [{"id": "A", "locator": str(path)}], "edges": []}
                original = coordinator._read_bytes
                calls, returned_bytes = [], []

                def intercepted(target):
                    first = not calls
                    calls.append(str(target))
                    if first and case == "file_symlink_race":
                        path.unlink()
                        path.symlink_to(outside_file)
                    elif first and case == "directory_symlink_race":
                        parent.rename(source_root / "moved")
                        parent.symlink_to(outside, target_is_directory=True)
                    value = original(target)
                    returned_bytes.append(len(value))
                    if first and case == "source_change":
                        path.write_bytes(coordinator.encode(dict(document, facts=[dict(record, value="changed")])))
                    return value

                coordinator._read_bytes = intercepted
                try:
                    result = coordinator.query(state, "A", source_root, START, END, strategy=strategy)
                finally:
                    coordinator._read_bytes = original
                expected = "full" if case == "read_bytes" else "partial"
                assert result["status"] == expected, (case, strategy, result)
                assert len(result["facts"]) == (1 if case == "read_bytes" else 0)
                assert result["metrics"]["source_bytes_read"] == sum(returned_bytes)
                if case == "cross_window_conflict":
                    assert result["conflicts"][0]["reason"] == "unresolved_version"
                if case == "json_boolean_number_conflict":
                    assert result["conflicts"][0]["reason"] == "conflicting_content"
                outcomes.append({"case": case, "strategy": strategy, "passed": True,
                                 "status": result["status"], "fact_count": len(result["facts"]),
                                 "actual_read_calls": len(calls), "actual_returned_bytes": sum(returned_bytes),
                                 "reported_bytes": result["metrics"]["source_bytes_read"],
                                 "failure_reasons": list(result["coverage"]["failed"].values()),
                                 "conflict_reasons": [conflict["reason"] for conflict in result["conflicts"]]})
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="保存新证据文件，拒绝覆盖")
    parser.add_argument("--seed", type=int, default=20261010)
    parser.add_argument("--cases", type=int, default=400)
    parser.add_argument("--nodes", type=int, default=12)
    parser.add_argument("--deep-nodes", type=int, default=1200)
    args = parser.parse_args()
    if min(args.cases, args.nodes, args.deep_nodes) < 1:
        parser.error("样本与节点数量必须为正数")
    if args.output.exists():
        parser.error("证据文件已存在，请使用新文件名保留历史")
    before = fingerprints()
    topology = topology_probes(args.seed, args.cases, args.nodes, args.deep_nodes)
    boundary = boundary_probes()
    after = fingerprints()
    evidence = {"created_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
                "parameters": {"seed": args.seed, "cases": args.cases, "nodes": args.nodes, "deep_nodes": args.deep_nodes},
                "source_sha256": before, "code_unchanged_during_run": before == after,
                "topology": topology, "boundary": boundary,
                "limitations": ["拓扑测试替换 _read_node 为确定性事实源；不验证源 I/O、存储或 Agent",
                                "边界探针使用真实临时文件并注入来源变化；不修改实现或现有测试",
                                "未验证真实模型、网络、令牌成本、分布式权限或全局源事务"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("独立探针：{} 个随机 DAG × 2 策略、{} 节点深链、{} 项来源边界，全部通过；源码稳定={}；证据 {}".format(
        args.cases, args.deep_nodes, len(boundary), before == after, args.output))
    return 0 if before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
