"""重现 P1 四格探索实验；计字节与程序耗时，不声称模型 token 或完整选型。"""
import argparse
import hashlib
import json
import platform
import sqlite3
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .coordinator import encode, manifest, paginate, query
    from .file_store import FileRegistry
    from .sqlite_store import SQLiteRegistry
else:
    from coordinator import encode, manifest, paginate, query
    from file_store import FileRegistry
    from sqlite_store import SQLiteRegistry


ROOT = Path(__file__).resolve().parent
START, END = "2026-10-05T00:00:00+08:00", "2026-10-12T00:00:00+08:00"


def fixture(directory, count, shape, facts_per_node):
    directory.mkdir(parents=True, exist_ok=True)
    nodes, edges, expected = [], [], {}
    fingerprints = {}
    for index in range(count):
        node_id = "n{:05d}".format(index)
        records = [{"record_id": "r{:04d}".format(offset), "revision": 1,
                    "occurred_at": "2026-10-07T12:00:00+08:00",
                    "value": {"title": "实验工作", "contribution": offset}}
                   for offset in range(facts_per_node)]
        expected.update({(node_id, record["record_id"]): {
            "revision": 1, "occurred_at": "2026-10-07T04:00:00+00:00", "value": record["value"]}
            for record in records})
        records.extend([
            {"record_id": "before", "revision": 1, "occurred_at": "2026-10-04T23:59:59+08:00", "value": "区间前"},
            {"record_id": "after", "revision": 1, "occurred_at": END, "value": "下周"},
        ])
        path = directory / (node_id + ".json")
        content = encode({"node_id": node_id, "view_id": "main", "facts": records})
        path.write_bytes(content)
        fingerprints[path.name] = hashlib.sha256(content).hexdigest()
        nodes.append({"id": node_id, "locator": str(path)})
        if index:
            parent = 0 if shape == "flat" else index - 1 if shape == "chain" else (index - 1) // 4
            edges.append({"source": "n{:05d}".format(parent), "target": node_id, "kind": "contains"})
            if shape == "diamond" and index > 2 and parent != index - 1:
                edges.append({"source": "n{:05d}".format(index - 1), "target": node_id, "kind": "contains"})
    digest = hashlib.sha256(encode({"files": fingerprints, "edges": edges})).hexdigest()
    return nodes, edges, expected, fingerprints, digest


def code_fingerprints():
    paths = list(ROOT.glob("*.py")) + [ROOT / "PLAN.md", ROOT / "CONTRACT.md"]
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def run_case(workspace, count, shape, facts_per_node, repeats, rows, datasets):
    workspace = Path(workspace).resolve()
    source = workspace / "sources" / ("{}-{}-{}".format(count, shape, facts_per_node))
    nodes, edges, expected, fingerprints, digest = fixture(source, count, shape, facts_per_node)
    datasets.append({"nodes": count, "shape": shape, "facts_per_node": facts_per_node,
                     "sha256": digest, "expected_facts": len(expected)})
    combinations = [("file", "central"), ("file", "hierarchical"),
                    ("sqlite", "central"), ("sqlite", "hierarchical")]
    # 四格每轮移位，避免固定让某个后端总在第一个或缓存最热时执行。
    for repetition in range(repeats):
        order = combinations[repetition % 4:] + combinations[:repetition % 4]
        for position, (backend, strategy) in enumerate(order):
            row = {"nodes": count, "shape": shape, "facts_per_node": facts_per_node,
                   "backend": backend, "strategy": strategy, "repetition": repetition,
                   "position": position, "dataset_sha256": digest, "status": "error"}
            rows.append(row)
            registry = None
            try:
                path = workspace / "registries" / ("{}-{}-{}-{}-{}-{}".format(
                    count, shape, facts_per_node, repetition, backend, strategy))
                cls = FileRegistry if backend == "file" else SQLiteRegistry
                registry = cls(path)
                started = time.perf_counter()
                registry.initialize(nodes, edges)
                row["initialize_ms"] = (time.perf_counter() - started) * 1000
                registry.close()
                registry = cls(path)
                started = time.perf_counter()
                snapshot = registry.snapshot()
                row["snapshot_ms"] = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                result = query(snapshot, "n00000", source, START, END, strategy=strategy)
                row["query_ms"] = (time.perf_counter() - started) * 1000
                actual = {(fact["origin_node_id"], fact["record_id"]) for fact in result["facts"]}
                row["missing_facts"] = len(set(expected) - actual)
                row["extra_facts"] = len(actual - set(expected))
                row["duplicate_facts"] = len(result["facts"]) - len(actual)
                mismatches = 0
                for fact in result["facts"]:
                    identity = (fact["origin_node_id"], fact["record_id"])
                    fields = {key: fact[key] for key in ("revision", "occurred_at", "value")}
                    source_name = fact["origin_node_id"] + ".json"
                    expected_sources = [{"path": str(source / source_name), "sha256": fingerprints.get(source_name)}]
                    if encode(fields) != encode(expected.get(identity)) or fact["sources"] != expected_sources:
                        mismatches += 1
                row["semantic_mismatches"] = mismatches
                row["query_status"] = result["status"]
                pages = paginate(result["facts"], max_bytes=4096)
                row["largest_page_bytes"] = max((len(encode(page)) for page in pages), default=0)
                row["page_count"] = len(pages)
                result_path = workspace / "results" / (path.name + ".json")
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_bytes(encode(result))
                row["result_artifact"] = str(result_path)
                row["result_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
                row["root_manifest_bytes"] = len(encode(manifest(result, result_path)))
                row["metrics"] = result["metrics"]
                # 局部定位修改无需更新其他节点；仍允许权威库自身采用不同写入布局。
                before = registry.snapshot()
                moved = dict(nodes[-1], locator=nodes[-1]["locator"] + ".moved")
                started = time.perf_counter()
                registry.apply(before["revision"], upsert_nodes=[moved])
                row["update_ms"] = (time.perf_counter() - started) * 1000
                after = registry.snapshot()
                changed = [a["id"] for a, b in zip(after["nodes"], before["nodes"]) if a != b]
                row["changed_node_records"] = changed
                row["relation_update_valid"] = after["edges"] == before["edges"] and changed == [moved["id"]]
                row["persistent_bytes"] = sum(item.stat().st_size for item in path.parent.glob(path.name + "*") if item.is_file())
                row["status"] = "pass" if (actual == set(expected) and not mismatches and not row["duplicate_facts"]
                    and result["status"] == "full" and row["relation_update_valid"]) else "fail"
            except Exception as error:
                row["error"] = "{}: {}".format(type(error).__name__, error)
            finally:
                if registry is not None:
                    registry.close()
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.glob("*.json")}
    if after != fingerprints:
        raise RuntimeError("查询修改了节点源文件，停止该轮实验")


def summarize(rows):
    groups = {}
    for row in rows:
        key = (row["nodes"], row["shape"], row["facts_per_node"], row["backend"], row["strategy"])
        groups.setdefault(key, []).append(row)
    summaries = []
    for key, samples in groups.items():
        item = dict(zip(("nodes", "shape", "facts_per_node", "backend", "strategy"), key))
        item["samples"] = len(samples)
        item["passed"] = sum(sample["status"] == "pass" for sample in samples)
        item["failed"] = len(samples) - item["passed"]
        item["timing_population"] = "passed_samples_only"
        for metric in ("initialize_ms", "snapshot_ms", "query_ms", "update_ms"):
            values = [sample[metric] for sample in samples if sample["status"] == "pass" and metric in sample]
            if values:
                item[metric] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
        summaries.append(item)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="新建证据 JSON 文件，拒绝覆盖")
    parser.add_argument("--sizes", nargs="+", type=int, default=[1, 10, 100, 1000])
    parser.add_argument("--shapes", nargs="+", choices=["flat", "balanced", "chain", "diamond"],
                        default=["flat", "balanced", "chain", "diamond"])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--facts-per-node", type=int, default=1)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("输出已存在，使用新运行文件名保留历史证据")
    if min(args.sizes + [args.repeats, args.facts_per_node]) < 1:
        parser.error("规模与重复次数必须为正数")
    workspace = Path(tempfile.mkdtemp(prefix="frontier-p1-"))
    rows, datasets = [], []
    before = code_fingerprints()
    for count in args.sizes:
        for shape in args.shapes:
            run_case(workspace, count, shape, args.facts_per_node, args.repeats, rows, datasets)
            print("已验证 {} 节点 / {} / {} 次四格运行".format(count, shape, args.repeats), flush=True)
    evidence = {
        "stage": "P1", "created_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "sqlite": sqlite3.sqlite_version, "cpu_arch": platform.machine()},
        "baseline_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "parameters": {"sizes": args.sizes, "shapes": args.shapes, "repeats": args.repeats,
                       "facts_per_node": args.facts_per_node, "seed": 20261010},
        "limitations": ["确定性执行器，不是真实 Agent", "字节数不是 token",
                        "关系读取为全量一致快照，不比较原生递归 SQL/Cypher",
                        "单机探索，未测全机断电或真实业务项目", "未清空操作系统缓存",
                        "源 JSON 是合成事实，不等于从实际 Markdown 完整提取"],
        "candidates": {"file": "measured", "sqlite": "measured",
                       "postgresql": "not_run/environment: Docker 服务不可用",
                       "neo4j": "not_run/environment: Docker 服务不可用"},
        "code_sha256": before, "code_unchanged_during_run": before == code_fingerprints(),
        "workspace": str(workspace), "datasets": datasets, "samples": rows, "summary": summarize(rows),
        "selection": "undecided",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    failed = sum(row["status"] != "pass" for row in rows)
    print("证据已写入 {}；{} 次运行，{} 次失败；本轮不选定后端".format(args.output, len(rows), failed))
    return 1 if failed or not evidence["code_unchanged_during_run"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
