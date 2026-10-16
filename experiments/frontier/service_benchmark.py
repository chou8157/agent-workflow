"""P2 本地/服务关系存储同台探测；包含真实服务查询和可选重启恢复证据。"""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__:
    from .file_store import FileRegistry
    from .sqlite_store import SQLiteRegistry
    from .service_stores import REGISTRIES, configured
else:
    from file_store import FileRegistry
    from sqlite_store import SQLiteRegistry
    from service_stores import REGISTRIES, configured


ROOT = Path(__file__).resolve().parent


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def redacted(value):
    dsn = os.environ.get("FRONTIER_PG_DSN", "")
    secrets = [dsn, unquote(urlparse(dsn).password or ""), os.environ.get("FRONTIER_NEO4J_PASSWORD", "")]
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            value = value.replace(secret, "<redacted>")
    return value


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        "service_stores.py", "service_benchmark.py", "test_service_stores.py", "storage_common.py",
        "file_store.py", "sqlite_store.py")}


def graph(count, shape):
    nodes = [{"id": "n{:05d}".format(i), "locator": "source-{}.json".format(i)} for i in range(count)]
    edges = []
    for index in range(1, count):
        parent = 0 if shape == "flat" else index - 1 if shape == "chain" else (index - 1) // 4
        edges.append({"source": nodes[parent]["id"], "target": nodes[index]["id"], "kind": "contains"})
        if shape == "diamond" and index > 2 and parent != index - 1:
            edges.append({"source": nodes[index - 1]["id"], "target": nodes[index]["id"], "kind": "contains"})
    return {"revision": 1, "nodes": nodes, "edges": edges}


def descendants(snapshot, root):
    # 独立集合闭包 oracle，不调用服务后端或协调器的遍历实现。
    selected = {root}
    while True:
        expanded = selected | {edge["target"] for edge in snapshot["edges"]
                               if edge["kind"] == "contains" and edge["source"] in selected}
        if expanded == selected:
            return sorted(selected)
        selected = expanded


def application_descendants(snapshot, root):
    adjacency = {}
    for edge in snapshot["edges"]:
        if edge["kind"] == "contains":
            adjacency.setdefault(edge["source"], []).append(edge["target"])
    selected, pending = set(), [root]
    while pending:
        node = pending.pop()
        if node in selected:
            continue
        selected.add(node)
        pending.extend(adjacency.get(node, ()))
    return sorted(selected)


def measured(call):
    started = time.perf_counter()
    value = call()
    return value, (time.perf_counter() - started) * 1000


def make_registry(backend, workspace):
    identity = "p2_bench_" + uuid.uuid4().hex
    if backend in REGISTRIES:
        return REGISTRIES[backend](identity), identity
    path = workspace / identity
    cls = FileRegistry if backend == "file" else SQLiteRegistry
    return cls(path), str(path)


def reopen(backend, identity):
    cls = REGISTRIES.get(backend, FileRegistry if backend == "file" else SQLiteRegistry)
    return cls(identity)


def run_matrix(args):
    workspace = Path(tempfile.mkdtemp(prefix="frontier-p2-services-", dir="/private/tmp"))
    available = [backend for backend in args.backends if backend not in REGISTRIES or configured(backend)]
    candidates = {backend: ("measured" if backend in available else "not_run/environment") for backend in args.backends}
    rows, information = [], {}
    for count in args.sizes:
        for shape in args.shapes:
            expected = graph(count, shape)
            digest = hashlib.sha256(encoded(expected)).hexdigest()
            roots = sorted({expected["nodes"][0]["id"], expected["nodes"][count // 2]["id"]})
            for repetition in range(args.repeats):
                offset = repetition % len(available) if available else 0
                order = available[offset:] + available[:offset]
                for position, backend in enumerate(order):
                    row = {"backend": backend, "nodes": count, "shape": shape, "repetition": repetition,
                           "position": position, "dataset_sha256": digest, "status": "error", "native_queries": []}
                    rows.append(row)
                    instance, identity = make_registry(backend, workspace)
                    restored = None
                    try:
                        _, row["initialize_ms"] = measured(lambda: instance.initialize(expected["nodes"], expected["edges"]))
                        instance.close()
                        instance = reopen(backend, identity)
                        current, row["snapshot_ms"] = measured(instance.snapshot)
                        assert current == dict(expected, edges=sorted(expected["edges"], key=lambda e: (e["source"], e["target"], e["kind"])))
                        repeated, row["repeat_snapshot_ms"] = measured(instance.snapshot)
                        assert repeated == current
                        row["snapshot_payload_bytes"] = len(encoded(current))
                        row["snapshot_queries"] = []
                        for root in roots:
                            wanted = descendants(expected, root)
                            selected, closure_ms = measured(lambda: application_descendants(current, root))
                            assert selected == wanted
                            row["snapshot_queries"].append({"root": root, "node_count": len(wanted), "python_closure_ms": closure_ms,
                                                            "snapshot_plus_closure_ms": row["snapshot_ms"] + closure_ms})
                            if backend in REGISTRIES:
                                native = {"root": root, "status": "error"}
                                row["native_queries"].append(native)
                                native_started = time.perf_counter()
                                try:
                                    answer, native["query_ms"] = measured(lambda: instance.descendants(root))
                                    native["semantic_match"] = answer == {"revision": 1, "node_ids": wanted}
                                    native["payload_bytes"] = len(encoded(answer))
                                    native["status"] = "pass" if native["semantic_match"] else "fail"
                                    assert native["semantic_match"], "原生后代查询与独立 oracle 不一致"
                                except Exception as error:
                                    native["error"] = redacted(type(error).__name__ + ": " + str(error))
                                    native["failed_after_ms"] = (time.perf_counter() - native_started) * 1000
                        moved = dict(expected["nodes"][-1], locator="changed.json")
                        revision, row["update_ms"] = measured(lambda: instance.apply(1, upsert_nodes=[moved]))
                        assert revision == 2
                        updated = instance.snapshot()
                        assert updated["revision"] == 2 and updated["edges"] == current["edges"]
                        assert [node for node in updated["nodes"] if node["id"] == moved["id"]] == [moved]
                        instance.close()
                        instance = reopen(backend, identity)
                        durable, row["reopen_snapshot_ms"] = measured(instance.snapshot)
                        assert durable == updated
                        if backend in REGISTRIES:
                            information.setdefault(backend, instance.server_info())
                            backup, row["logical_backup_ms"] = measured(instance.logical_backup)
                            restored = REGISTRIES[backend]("p2_restore_" + uuid.uuid4().hex)
                            _, row["logical_restore_ms"] = measured(lambda: restored.restore(backup))
                            assert restored.snapshot() == updated
                            row["backup_sha256"] = backup["sha256"]
                        row["native_failures"] = sum(item["status"] != "pass" for item in row["native_queries"])
                        row["storage_contract_passed"] = True
                        row["status"] = "fail" if row["native_failures"] else "pass"
                    except Exception as error:
                        row["error"] = redacted(type(error).__name__ + ": " + str(error))
                    finally:
                        for cleanup in (restored, instance):
                            if cleanup is None:
                                continue
                            try:
                                if backend in REGISTRIES:
                                    cleanup.delete_test_registry()
                            except FileNotFoundError:
                                pass
                            except Exception as error:
                                row["cleanup_error"] = redacted(type(error).__name__ + ": " + str(error))
                                row["status"] = "error"
                            finally:
                                cleanup.close()
            print("P2 已执行 {} 节点 / {} / {} 次轮换".format(count, shape, args.repeats), flush=True)
    summary = []
    for backend in available:
        for count in args.sizes:
            for shape in args.shapes:
                samples = [row for row in rows if (row["backend"], row["nodes"], row["shape"]) == (backend, count, shape)]
                item = {"backend": backend, "nodes": count, "shape": shape, "samples": len(samples),
                        "passed": sum(row["status"] == "pass" for row in samples), "timing_population": "passed_samples_only"}
                for metric in ("initialize_ms", "snapshot_ms", "repeat_snapshot_ms", "update_ms", "reopen_snapshot_ms", "logical_backup_ms", "logical_restore_ms"):
                    values = [row[metric] for row in samples if row["status"] == "pass" and metric in row]
                    if values:
                        item[metric] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
                summary.append(item)
    return {"kind": "p2_service_matrix", "candidates": candidates, "server_info": information,
            "application_query_strategy": "adjacency_traversal_including_index_build",
            "oracle_strategy": "independent_repeated_set_closure_not_used_as_performance_baseline",
            "workspace": str(workspace), "samples": rows, "summary": summary}


def recovery(args):
    if args.verify_recovery:
        previous = json.loads(args.verify_recovery.read_text(encoding="utf-8"))
        if previous.get("kind") != "p2_service_restart_seed":
            raise ValueError("重启证据输入格式不符")
        rows = []
        for original in previous["registries"]:
            backend = original["backend"]
            instance = REGISTRIES[backend](original["namespace"])
            try:
                value = instance.snapshot()
                rows.append({"backend": backend, "namespace": original["namespace"],
                             "snapshot_preserved": value == original["snapshot"], "snapshot": value,
                             "server_info": instance.server_info()})
            finally:
                instance.close()
        return {"kind": "p2_service_restart_verify", "seed_file": str(args.verify_recovery), "registries": rows}
    rows = []
    for backend in args.backends:
        if backend not in REGISTRIES or not configured(backend):
            continue
        instance = REGISTRIES[backend]("p2_recovery_" + uuid.uuid4().hex)
        try:
            value = graph(4, "diamond")
            instance.initialize(value["nodes"], value["edges"])
            instance.apply(1, upsert_nodes=[{"id": "n00000", "locator": "committed-before-restart.json"}])
            rows.append({"backend": backend, "namespace": instance.namespace, "snapshot": instance.snapshot(),
                         "backup": instance.logical_backup(), "server_info": instance.server_info()})
        finally:
            instance.close()
    return {"kind": "p2_service_restart_seed", "registries": rows,
            "note": "仅播种已提交数据；需要外部实际重启专用服务后再执行 verify，播种本身不证明重启恢复"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="新建证据 JSON，拒绝覆盖旧运行")
    parser.add_argument("--backends", nargs="+", choices=["file", "sqlite", "postgresql", "neo4j"],
                        default=["file", "sqlite", "postgresql", "neo4j"])
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 100])
    parser.add_argument("--shapes", nargs="+", choices=["flat", "balanced", "chain", "diamond"], default=["flat", "balanced", "chain", "diamond"])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--run-tests", action="store_true", help="先运行真实服务契约测试并保存输出")
    parser.add_argument("--seed-recovery", action="store_true", help="留下专用命名空间，供外部重启服务后核验")
    parser.add_argument("--verify-recovery", type=Path, help="读取此前播种证据，验证实际重启后的数据")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("证据文件已存在，请使用新路径")
    if min(args.sizes + [args.repeats]) < 1 or (args.seed_recovery and args.verify_recovery):
        parser.error("规模/重复数必须为正数，播种与复核不能同时使用")
    before = hashes()
    evidence = {"stage": "P2", "created_at": datetime.now(timezone.utc).isoformat(),
                "environment": {"python": platform.python_version(), "platform": platform.platform()},
                "parameters": {"backends": args.backends, "sizes": args.sizes, "shapes": args.shapes, "repeats": args.repeats},
                "code_sha256": before,
                "limitations": ["只连接显式启用的本机专用实例，不代表跨主机/生产性能",
                                "本矩阵只比关系存储与后代集合，不调用模型、不统计 token",
                                "Neo4j 一致快照通过元节点锁实现，需要写事务权限并会串行化同一 registry 读取",
                                "原生查询只返回节点ID，独立报告与全快照载荷差异；未宣称两者传输内容相同",
                                "逻辑备份不代替服务原生物理备份或节点事实备份；提交确认丢失未做网络故障实测",
                                "保留所有样本；5次探索不估可靠P95，不决定赢家"]}
    if args.run_tests:
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-m", "pytest", str(ROOT / "test_service_stores.py"), "-q", "-p", "no:cacheprovider", "--tb=short"]
        result = subprocess.run(command, cwd=str(ROOT.parent.parent), env=environment, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        evidence["contract_tests"] = {"command": command, "exit_code": result.returncode, "output": redacted(result.stdout)}
    evidence.update(recovery(args) if args.seed_recovery or args.verify_recovery else run_matrix(args))
    evidence["code_unchanged_during_run"] = before == hashes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    failed = any(row["status"] != "pass" for row in evidence.get("samples", []))
    failed = failed or any(not row["snapshot_preserved"] for row in evidence.get("registries", []) if "snapshot_preserved" in row)
    failed = failed or evidence.get("contract_tests", {}).get("exit_code", 0) != 0 or not evidence["code_unchanged_during_run"]
    print("P2 证据已保存：{}；失败={}；不决定后端".format(args.output, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
