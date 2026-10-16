"""P2 本地候选实测：真实进程故障、备份迁移及原生查询；不接入稳定产品。"""

import argparse
import hashlib
import json
import multiprocessing
import os
import platform
import resource
import signal
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .file_store import FileRegistry
    from .sqlite_store import SQLiteRegistry
    from .storage_common import RevisionConflict, normalize, validate
else:
    from file_store import FileRegistry
    from sqlite_store import SQLiteRegistry
    from storage_common import RevisionConflict, normalize, validate


BACKENDS = {"F": FileRegistry, "S": SQLiteRegistry}
SUFFIXES = {"F": ".json", "S": ".sqlite"}
CONTEXT = multiprocessing.get_context("spawn")
CTE = """WITH RECURSIVE reachable(id) AS (
    SELECT id FROM nodes WHERE id=?
    UNION
    SELECT e.target FROM edges AS e JOIN reachable AS r ON e.source=r.id
    WHERE e.kind='contains'
) """


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def fixture(size):
    nodes = [{"id": "n{:05d}".format(index), "locator": "source/{:05d}.json".format(index)}
             for index in range(size)]
    edges = [{"source": nodes[(index - 1) // 4]["id"], "target": nodes[index]["id"], "kind": "contains"}
             for index in range(1, size)]
    return nodes, edges


def expected_tree(size, root_index):
    # 独立 oracle 根据节点编号逐个判断祖先，不调用任一候选查询或共享图遍历。
    selected = set()
    for index in range(size):
        ancestor = index
        while ancestor > root_index:
            ancestor = (ancestor - 1) // 4
        if ancestor == root_index:
            selected.add(index)
    return {
        "revision": 1,
        "nodes": [{"id": "n{:05d}".format(index), "locator": "source/{:05d}.json".format(index)}
                  for index in sorted(selected)],
        "edges": sorted([
            {"source": "n{:05d}".format((index - 1) // 4), "target": "n{:05d}".format(index), "kind": "contains"}
            for index in selected if index > 0 and (index - 1) // 4 in selected
        ], key=lambda edge: (edge["source"], edge["target"], edge["kind"])),
    }


def initialize(backend, path, size=2):
    registry = BACKENDS[backend](path)
    nodes, edges = fixture(size)
    registry.initialize(nodes, edges)
    registry.close()


def receive(connection, timeout=30):
    if not connection.poll(timeout):
        raise TimeoutError("实验子进程未在限时内响应")
    return connection.recv()


def finish(process, timeout=15):
    process.join(timeout)
    if process.is_alive():
        raise TimeoutError("实验子进程未在限时内结束")
    if process.exitcode != 0:
        raise RuntimeError("实验子进程失败：{}".format(process.exitcode))


def cleanup_process(process):
    if process.pid is not None:
        if process.is_alive():
            process.kill()
        process.join(5)


def _cas_worker(backend, path, index, barrier, connection):
    registry = BACKENDS[backend](path)
    connection.send({"stage": "ready", "pid": os.getpid()})
    barrier.wait(30)
    start = time.perf_counter()
    try:
        revision = registry.apply(1, upsert_nodes=[{"id": "writer-{:02d}".format(index), "locator": "writer.json"}])
        result = {"status": "committed", "revision": revision, "index": index}
    except RevisionConflict:
        result = {"status": "conflict", "index": index}
    except Exception as error:
        result = {"status": "error", "error": repr(error), "index": index}
    result.update({"elapsed_seconds": time.perf_counter() - start, "pid": os.getpid()})
    connection.send(result)
    connection.close()
    registry.close()


def cas_competition(backend, path, writers=16):
    initialize(backend, path)
    barrier = CONTEXT.Event()
    processes, receivers = [], []
    started = time.perf_counter()
    try:
        for index in range(writers):
            receiver, sender = CONTEXT.Pipe(duplex=False)
            process = CONTEXT.Process(target=_cas_worker, args=(backend, str(path), index, barrier, sender))
            process.start()
            sender.close()
            processes.append(process)
            receivers.append(receiver)
        ready = [receive(receiver) for receiver in receivers]
        barrier.set()
        outcomes = [receive(receiver) for receiver in receivers]
        for process in processes:
            finish(process)
        snapshot = BACKENDS[backend](path).snapshot()
        winners = [outcome for outcome in outcomes if outcome["status"] == "committed"]
        conflicts = sum(outcome["status"] == "conflict" for outcome in outcomes)
        correct = (len(winners) == 1 and conflicts == writers - 1 and snapshot["revision"] == 2
                   and len(snapshot["nodes"]) == 3 and len(snapshot["edges"]) == 1)
        return {"backend": backend, "writers": writers, "ready": ready, "outcomes": outcomes,
                "passed": correct, "final_revision": snapshot["revision"],
                "snapshot_sha256": fingerprint(snapshot), "elapsed_seconds": time.perf_counter() - started}
    finally:
        barrier.set()
        for process in processes:
            cleanup_process(process)
        for receiver in receivers:
            receiver.close()


def _park(connection, stage):
    connection.send({"stage": stage, "pid": os.getpid(), "wall_time_ns": time.time_ns()})
    while True:
        signal.pause()


class CommitProbe:
    def __init__(self, connection, before=None, after=None):
        self.connection, self.before, self.after = connection, before, after

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def commit(self):
        if self.before:
            self.before()
        result = self.connection.commit()
        if self.after:
            self.after(self.connection)
        return result


def _kill_worker(backend, path, stage, connection):
    registry = BACKENDS[backend](path)
    if backend == "F" and stage == "before_commit":
        original_replace = os.replace

        def stop_before_replace(source, target):
            _park(connection, stage)
            return original_replace(source, target)

        os.replace = stop_before_replace
    elif backend == "F":
        original_write = registry._write

        def stop_after_write(value):
            original_write(value)
            _park(connection, stage)

        registry._write = stop_after_write
    else:
        original_connect = registry._connect

        def probed_connect(*args, **kwargs):
            return CommitProbe(original_connect(*args, **kwargs),
                               before=(lambda: _park(connection, stage)) if stage == "before_commit" else None,
                               after=(lambda _: _park(connection, stage)) if stage == "after_commit" else None)

        registry._connect = probed_connect
    registry.apply(1, upsert_nodes=[{"id": "n00000", "locator": "committed.json"}])
    connection.send({"stage": "unexpected_return"})


def kill_recovery(backend, path, stage):
    initialize(backend, path)
    original = BACKENDS[backend](path).snapshot()
    receiver, sender = CONTEXT.Pipe(duplex=False)
    process = CONTEXT.Process(target=_kill_worker, args=(backend, str(path), stage, sender))
    process.start()
    sender.close()
    try:
        marker = receive(receiver)
        if marker["stage"] != stage or marker["pid"] != process.pid:
            raise AssertionError("强杀边界未按预期到达")
        kill_at = time.time_ns()
        os.kill(process.pid, signal.SIGKILL)
        process.join(15)
        if process.is_alive() or process.exitcode != -signal.SIGKILL:
            raise AssertionError("子进程未以真实 SIGKILL 结束")
        recovered = BACKENDS[backend](path).snapshot()
        expected = json.loads(json.dumps(original))
        if stage == "after_commit":
            expected["revision"] = 2
            expected["nodes"][0]["locator"] = "committed.json"
        recovery_correct = recovered == expected
        continued = BACKENDS[backend](path).apply(recovered["revision"])
        leftovers = sorted(item.name for item in Path(path).parent.glob("." + Path(path).name + ".*.tmp"))
        return {"backend": backend, "stage": stage, "pid": process.pid, "signal": "SIGKILL",
                "exit_code": process.exitcode, "marker": marker, "kill_wall_time_ns": kill_at,
                "passed": recovery_correct and continued == expected["revision"] + 1,
                "recovered_revision": recovered["revision"], "continued_revision": continued,
                "recovered_snapshot_sha256": fingerprint(recovered), "expected_snapshot_sha256": fingerprint(expected),
                "orphan_temporary_files": leftovers,
                "scope": "真实进程强杀；未模拟系统断电、设备缓存丢失或文件系统损坏"}
    finally:
        cleanup_process(process)
        receiver.close()


def backup(backend, source_path, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("备份目标已存在")
    if backend == "F":
        registry = FileRegistry(source_path)
        with registry._locked(exclusive=False):
            content = registry.path.read_bytes()
            validate(json.loads(content))
            with destination.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    else:
        source = sqlite3.connect(Path(source_path).resolve().as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(str(destination))
        try:
            target.execute("PRAGMA synchronous=FULL")
            source.backup(target, pages=8, sleep=0.001)
            target.execute("PRAGMA journal_mode=WAL")
            target.commit()
        finally:
            target.close()
            source.close()
    return BACKENDS[backend](destination).snapshot()


def _backup_writer(backend, path, updates, connection, completed):
    registry = BACKENDS[backend](path)
    start = time.time_ns()
    connection.send({"stage": "writing", "start": start, "pid": os.getpid()})
    for revision in range(1, updates + 1):
        registry.apply(revision, upsert_nodes=[{"id": "n00000", "locator": "rev:{}".format(revision + 1)}])
        time.sleep(0.005)
    completed.set()
    connection.send({"stage": "finished", "start": start, "end": time.time_ns(), "updates": updates})


def concurrent_backups(backend, directory, count=5, updates=30):
    directory = Path(directory)
    path = directory / ("live" + SUFFIXES[backend])
    registry = BACKENDS[backend](path)
    nodes, edges = fixture(100)
    nodes[0]["locator"] = "rev:1"
    registry.initialize(nodes, edges)
    receiver, sender = CONTEXT.Pipe(duplex=False)
    completed = CONTEXT.Event()
    process = CONTEXT.Process(target=_backup_writer, args=(backend, str(path), updates, sender, completed))
    process.start()
    sender.close()
    samples = []
    try:
        marker = receive(receiver)
        for index in range(count):
            started = time.time_ns()
            writer_active = not completed.is_set()
            destination = directory / ("backup-{}".format(index) + SUFFIXES[backend])
            snapshot = backup(backend, path, destination)
            ended = time.time_ns()
            restored = backup(backend, destination, directory / ("restore-{}".format(index) + SUFFIXES[backend]))
            correct = (snapshot == restored and snapshot["nodes"][0]["locator"] == "rev:{}".format(snapshot["revision"])
                       and snapshot["edges"] == edges and len(snapshot["nodes"]) == 100)
            samples.append({"index": index, "start": started, "end": ended, "revision": snapshot["revision"],
                            "writer_active_when_backup_started": writer_active,
                            "consistent_and_restored": correct, "snapshot_sha256": fingerprint(snapshot)})
        completion = receive(receiver)
        finish(process)
        # 本机 Python 3.8 的 monotonic 起点可能按进程不同，用 IPC 事件确认并发区间。
        overlaps = [sample["writer_active_when_backup_started"] for sample in samples]
        return {"backend": backend, "passed": all(sample["consistent_and_restored"] for sample in samples) and any(overlaps),
                "writer": completion, "samples": samples, "overlaps_writer_interval": overlaps,
                "final_revision": registry.snapshot()["revision"]}
    finally:
        cleanup_process(process)
        receiver.close()


def import_snapshot(backend, destination, snapshot):
    """显式离线导入，临时权威验证完毕后发布；保留导出 revision，不伪造 apply 历史。"""
    validate(snapshot)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(str(destination)):
        raise FileExistsError("迁移目标已存在，拒绝覆盖")
    temporary_directory = Path(tempfile.mkdtemp(prefix="p2-import-", dir=str(destination.parent)))
    staged = temporary_directory / ("authority" + SUFFIXES[backend])
    registry = BACKENDS[backend](staged)
    registry.initialize(snapshot["nodes"], snapshot["edges"])
    if backend == "F":
        with registry._locked(exclusive=True):
            registry._write(normalize(snapshot))
    else:
        connection = registry._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE meta SET revision=? WHERE singleton=1", (snapshot["revision"],))
            connection.commit()
        finally:
            connection.close()
    if registry.snapshot() != normalize(snapshot):
        raise AssertionError("迁移临时权威与导出内容不一致")
    registry.close()
    os.link(str(staged), str(destination))
    staged.unlink()
    descriptor = os.open(str(destination.parent), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return BACKENDS[backend](destination).snapshot()


def migration_roundtrip(start_backend, directory):
    directory = Path(directory)
    first = directory / ("start" + SUFFIXES[start_backend])
    initialize(start_backend, first, 100)
    registry = BACKENDS[start_backend](first)
    for revision in range(1, 5):
        registry.apply(revision, upsert_nodes=[{"id": "n00000", "locator": "migration-{}.json".format(revision)}])
    exported = registry.snapshot()
    source_hash = fingerprint(exported)
    other = "S" if start_backend == "F" else "F"
    imported = import_snapshot(other, directory / ("middle" + SUFFIXES[other]), exported)
    returned = import_snapshot(start_backend, directory / ("returned" + SUFFIXES[start_backend]), imported)
    return {"direction": start_backend + "->" + other + "->" + start_backend,
            "passed": exported == imported == returned and registry.snapshot() == exported,
            "revision": exported["revision"], "source_sha256": source_hash,
            "middle_sha256": fingerprint(imported), "returned_sha256": fingerprint(returned),
            "method": "新权威离线导入；保留 revision，原生写锁/事务，核对后以独占 hard-link 发布；不改既有 API"}


def query_file(path, root):
    registry = FileRegistry(path)
    with registry._locked(exclusive=False):
        snapshot = json.loads(registry.path.read_bytes())
    by_id = {node["id"]: node for node in snapshot["nodes"]}
    if root not in by_id:
        raise ValueError("查询根节点不存在")
    children = {}
    for edge in snapshot["edges"]:
        if edge["kind"] == "contains":
            children.setdefault(edge["source"], []).append(edge["target"])
    selected, pending = set(), [root]
    while pending:
        node = pending.pop()
        if node not in selected:
            selected.add(node)
            pending.extend(children.get(node, []))
    return {"revision": snapshot["revision"], "nodes": [by_id[node] for node in sorted(selected)],
            "edges": sorted([edge for edge in snapshot["edges"]
                             if edge["source"] in selected and edge["target"] in selected],
                            key=lambda edge: (edge["source"], edge["target"], edge["kind"]))}


def query_sqlite(path, root):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("BEGIN")
        revision = connection.execute("SELECT revision FROM meta WHERE singleton=1").fetchone()[0]
        nodes = [{"id": row[0], "locator": row[1]} for row in connection.execute(
            CTE + "SELECT n.id,n.locator FROM nodes n JOIN reachable r ON n.id=r.id ORDER BY n.id", (root,))]
        if not nodes:
            raise ValueError("查询根节点不存在")
        edges = [{"source": row[0], "target": row[1], "kind": row[2]} for row in connection.execute(
            CTE + "SELECT e.source,e.target,e.kind FROM edges e JOIN reachable a ON e.source=a.id "
            "JOIN reachable b ON e.target=b.id ORDER BY e.source,e.target,e.kind", (root,))]
        connection.commit()
        return {"revision": revision, "nodes": nodes, "edges": edges}
    finally:
        connection.close()


def measured(call):
    before = resource.getrusage(resource.RUSAGE_SELF)
    start = time.perf_counter_ns()
    value = call()
    elapsed = time.perf_counter_ns() - start
    after = resource.getrusage(resource.RUSAGE_SELF)
    rss_factor = 1 if sys.platform == "darwin" else 1024
    return value, {"wall_ns": elapsed, "cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                   "process_peak_rss_bytes": after.ru_maxrss * rss_factor,
                   "minor_faults_delta": after.ru_minflt - before.ru_minflt,
                   "major_faults_delta": after.ru_majflt - before.ru_majflt,
                   "block_input_ops_delta": after.ru_inblock - before.ru_inblock,
                   "block_output_ops_delta": after.ru_oublock - before.ru_oublock}


def summarize(samples):
    times = [sample["wall_ns"] for sample in samples]
    return {"samples": len(times), "median_wall_ns": statistics.median(times), "min_wall_ns": min(times), "max_wall_ns": max(times)}


def query_benchmark(directory, sizes=(1, 100, 1000), repetitions=5):
    directory = Path(directory)
    cells = []
    for size in sizes:
        paths = {backend: directory / ("{}-{}".format(backend, size) + SUFFIXES[backend]) for backend in BACKENDS}
        for backend in BACKENDS:
            initialize(backend, paths[backend], size)
            BACKENDS[backend](paths[backend]).snapshot()
        for scope, root_index in (("narrow", max(0, (size - 2) // 4)), ("full", 0)):
            expected = expected_tree(size, root_index)
            root = "n{:05d}".format(root_index)
            by_backend = {backend: {"backend": backend, "nodes": size, "scope": scope, "root": root,
                                    "result_node_count": len(expected["nodes"]), "result_edge_count": len(expected["edges"]),
                                    "expected_sha256": fingerprint(expected), "result_bytes": len(canonical(expected)), "raw_samples": []}
                          for backend in BACKENDS}
            for repetition in range(repetitions + 1):
                order = ("F", "S") if repetition % 2 == 0 else ("S", "F")
                for backend in order:
                    query = query_file if backend == "F" else query_sqlite
                    value, sample = measured(lambda: query(paths[backend], root))
                    sample.update({"repetition": repetition, "order": list(order), "correct": value == expected,
                                   "result_sha256": fingerprint(value)})
                    if repetition == 0:
                        by_backend[backend]["first_native_call"] = sample
                    else:
                        by_backend[backend]["raw_samples"].append(sample)
            for backend, cell in by_backend.items():
                cell["summary"] = summarize(cell["raw_samples"])
                cell["passed"] = cell["first_native_call"]["correct"] and all(sample["correct"] for sample in cell["raw_samples"])
                cell["authority_file_bytes"] = paths[backend].stat().st_size
                if backend == "F":
                    cell["decoded_authority_bytes_per_query"] = paths[backend].stat().st_size
                else:
                    with sqlite3.connect(str(paths[backend])) as connection:
                        cell["query_plan"] = connection.execute("EXPLAIN QUERY PLAN " + CTE +
                            "SELECT n.id,n.locator FROM nodes n JOIN reachable r ON n.id=r.id ORDER BY n.id", (root,)).fetchall()
                cells.append(cell)
    return {"passed": all(cell["passed"] for cell in cells), "repetitions": repetitions, "cells": cells,
            "method": "同一持久化图、同一输出字段与独立 oracle；每格首次原生调用单列，之后至少 5 次，轮换 F/S 顺序；不清 OS 缓存",
            "integrity_scope": "计时前两候选完整自检；查询假设权威由有效写者维护。F 读锁后全 JSON 解码扫描，S 单读事务递归 CTE；计时内均不重复完整 DAG 校验",
            "resource_limit": "RSS 为当前进程累计峰值，不是独立查询净内存；block counters 为 OS 提供计数，不当作设备真实写入字节；不报告 p95"}


def write_benchmark(directory, sizes=(1, 100, 1000), repetitions=5):
    cells = []
    for size in sizes:
        registries = {}
        for backend in BACKENDS:
            path = Path(directory) / ("write-{}-{}".format(backend, size) + SUFFIXES[backend])
            initialize(backend, path, size)
            registries[backend] = BACKENDS[backend](path)
        samples = {backend: [] for backend in BACKENDS}
        for repetition in range(repetitions):
            order = ("F", "S") if repetition % 2 == 0 else ("S", "F")
            for backend in order:
                registry = registries[backend]
                observation = {}
                if backend == "S":
                    original_connect = registry._connect

                    def observe_commit(connection):
                        wal = Path(str(registry.path) + "-wal")
                        observation.update({"sql_rows_changed": connection.total_changes,
                                            "wal_bytes_after_commit": wal.stat().st_size if wal.exists() else 0})

                    registry._connect = lambda *args, **kwargs: CommitProbe(original_connect(*args, **kwargs), after=observe_commit)
                update = {"id": "n{:05d}".format(size - 1), "locator": "updated-{}.json".format(repetition)}
                try:
                    revision, sample = measured(lambda: registry.apply(repetition + 1, upsert_nodes=[update]))
                finally:
                    if backend == "S":
                        registry._connect = original_connect
                sample.update({"repetition": repetition, "order": list(order), "revision": revision,
                               "input_delta_bytes": len(canonical(update)), "authority_file_bytes": registry.path.stat().st_size,
                               "correct": revision == repetition + 2})
                if backend == "F":
                    sample["serialized_full_snapshot_bytes"] = registry.path.stat().st_size
                else:
                    sample.update(observation)
                samples[backend].append(sample)
        for backend in BACKENDS:
            final = registries[backend].snapshot()
            expected_nodes, expected_edges = fixture(size)
            expected_nodes[-1]["locator"] = "updated-{}.json".format(repetitions - 1)
            expected = {"revision": repetitions + 1, "nodes": expected_nodes, "edges": sorted(expected_edges, key=lambda edge: (edge["source"], edge["target"], edge["kind"]))}
            cells.append({"backend": backend, "nodes": size, "raw_samples": samples[backend], "summary": summarize(samples[backend]),
                          "passed": final == expected and all(sample["correct"] for sample in samples[backend])})
    return {"passed": all(cell["passed"] for cell in cells), "cells": cells,
            "bytes_scope": "F 为每次序列化并 fsync 的完整快照字节；S 为提交后关闭连接前 WAL 文件字节（含头/页），不是实际 SSD 写放大；两者不等同磁盘物理写入"}


def run(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    results = {"schema_version": 1, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
               "fixture_root": str(directory), "environment": {"python": sys.version, "python_executable": sys.executable,
               "platform": platform.platform(), "sqlite_version": sqlite3.sqlite_version, "cpu_count": os.cpu_count()},
               "cas": [], "kill_recovery": [], "backups": [], "migration": []}
    source_directory = Path(__file__).resolve().parent
    results["implementation_sha256"] = {
        name: hashlib.sha256((source_directory / name).read_bytes()).hexdigest()
        for name in ("p2_local.py", "file_store.py", "sqlite_store.py", "storage_common.py")}
    results["dataset"] = "固定编号 4 叉树；独立 oracle 逐个反查编号祖先；另有菱形多父与 related 不扩展测试"
    for backend in BACKENDS:
        print("执行 {}：16 进程 CAS 与真实强杀".format(backend), flush=True)
        results["cas"].append(cas_competition(backend, directory / ("cas-" + backend + SUFFIXES[backend])))
        for stage in ("before_commit", "after_commit"):
            results["kill_recovery"].append(kill_recovery(backend, directory / (backend + "-" + stage + SUFFIXES[backend]), stage))
        results["backups"].append(concurrent_backups(backend, directory / ("backup-" + backend)))
        results["migration"].append(migration_roundtrip(backend, directory / ("migration-" + backend)))
    print("执行原生查询与局部更新矩阵：1/100/1000 节点，每格 5 次", flush=True)
    results["query_benchmark"] = query_benchmark(directory / "query")
    results["write_benchmark"] = write_benchmark(directory / "write")
    results["passed"] = (all(item["passed"] for group in ("cas", "kill_recovery", "backups", "migration") for item in results[group])
                         and results["query_benchmark"]["passed"] and results["write_benchmark"]["passed"])
    results["not_validated"] = ["系统断电和设备缓存丢失", "网络文件系统", "跨机器事务", "文件日志/分片变体", "原生查询恶意绕过写入协议后的全局损坏检测"]
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="原始 JSON 证据路径")
    parser.add_argument("--fixtures", type=Path, help="新建隔离 fixture 根；省略时使用 /private/tmp")
    args = parser.parse_args()
    directory = args.fixtures or Path(tempfile.mkdtemp(prefix="frontier-p2-local-", dir="/private/tmp"))
    results = run(directory)
    results["command"] = [sys.executable] + sys.argv
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": results["passed"], "evidence": str(args.output), "fixture_root": str(directory)}, ensure_ascii=False))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
