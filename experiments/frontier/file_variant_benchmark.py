"""F / S / F-log 同口径工作负载与文件日志恢复实验。"""

import argparse
import hashlib
import json
import multiprocessing
import os
import platform
import signal
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .file_store import FileRegistry
    from .sqlite_store import SQLiteRegistry
    from .storage_common import RevisionConflict
    from .log_store import LogRegistry, UncommittedTailError, CorruptCommittedError
    from .p2_local import fixture, expected_tree, query_file, query_sqlite, measured, summarize, fingerprint, receive, finish, cleanup_process, CommitProbe
else:
    from file_store import FileRegistry
    from sqlite_store import SQLiteRegistry
    from storage_common import RevisionConflict
    from log_store import LogRegistry, UncommittedTailError, CorruptCommittedError
    from p2_local import fixture, expected_tree, query_file, query_sqlite, measured, summarize, fingerprint, receive, finish, cleanup_process, CommitProbe


BACKENDS = {"F": FileRegistry, "S": SQLiteRegistry, "F-log": LogRegistry}
CONTEXT = multiprocessing.get_context("spawn")


def query_log(path, root):
    snapshot = LogRegistry(path).snapshot()
    nodes = {node["id"]: node for node in snapshot["nodes"]}
    if root not in nodes:
        raise ValueError("查询根节点不存在")
    children = {}
    for edge in snapshot["edges"]:
        if edge["kind"] == "contains":
            children.setdefault(edge["source"], []).append(edge["target"])
    selected, todo = set(), [root]
    while todo:
        node = todo.pop()
        if node not in selected:
            selected.add(node)
            todo.extend(children.get(node, []))
    return {"revision": snapshot["revision"], "nodes": [nodes[node] for node in sorted(selected)],
            "edges": [edge for edge in snapshot["edges"] if edge["source"] in selected and edge["target"] in selected]}


def authority_bytes(backend, path):
    if backend != "F-log":
        return Path(path).stat().st_size
    return sum((Path(path) / name).stat().st_size for name in ("snapshot.json", "journal.log", "head.json"))


def _cas_worker(path, index, start, connection):
    registry = LogRegistry(path)
    connection.send({"stage": "ready", "pid": os.getpid()})
    if not start.wait(30):
        raise TimeoutError("未收到并发开始信号")
    try:
        revision = registry.apply(1, upsert_nodes=[{"id": "writer-{:02d}".format(index), "locator": "writer.json"}])
        connection.send({"status": "committed", "revision": revision, "index": index, "pid": os.getpid()})
    except RevisionConflict:
        connection.send({"status": "conflict", "index": index, "pid": os.getpid()})
    except Exception as error:
        connection.send({"status": "error", "error": repr(error), "index": index, "pid": os.getpid()})


def log_cas(path, writers=16):
    registry = LogRegistry(path)
    nodes, edges = fixture(2)
    registry.initialize(nodes, edges)
    start, processes, receivers = CONTEXT.Event(), [], []
    try:
        for index in range(writers):
            receiver, sender = CONTEXT.Pipe(duplex=False)
            process = CONTEXT.Process(target=_cas_worker, args=(str(path), index, start, sender))
            process.start()
            sender.close()
            processes.append(process)
            receivers.append(receiver)
        ready = [receive(connection) for connection in receivers]
        start.set()
        outcomes = [receive(connection) for connection in receivers]
        for process in processes:
            finish(process)
        winners = [item for item in outcomes if item["status"] == "committed"]
        correct = len(winners) == 1 and sum(item["status"] == "conflict" for item in outcomes) == writers - 1
        expected_nodes = nodes + ([{"id": "writer-{:02d}".format(winners[0]["index"]), "locator": "writer.json"}] if winners else [])
        expected = {"revision": 2, "nodes": sorted(expected_nodes, key=lambda node: node["id"]), "edges": edges}
        return {"writers": writers, "ready": ready, "outcomes": outcomes,
                "passed": correct and registry.snapshot() == expected, "expected_sha256": fingerprint(expected)}
    finally:
        start.set()
        for process in processes:
            cleanup_process(process)
        for connection in receivers:
            connection.close()


def _park(connection, stage):
    connection.send({"stage": stage, "pid": os.getpid(), "wall_time_ns": time.time_ns()})
    while True:
        signal.pause()


def _kill_worker(path, stage, connection):
    registry = LogRegistry(path)
    if stage == "partial_record":
        def partial_record(content):
            with (registry.path / "journal.log").open("ab") as stream:
                stream.write(content[:len(content) // 2])
                stream.flush()
                os.fsync(stream.fileno())
            _park(connection, stage)
        registry._append_record = partial_record
    else:
        original = registry._publish_head
        def head_boundary(head):
            if stage == "before_head":
                _park(connection, stage)
            original(head)
            _park(connection, stage)
        registry._publish_head = head_boundary
    registry.apply(2, upsert_nodes=[{"id": "n00000", "locator": "new-commit.json"}])
    raise AssertionError("强杀停驻点没有触发")


def log_kill_recovery(path, stage):
    registry = LogRegistry(path)
    nodes, edges = fixture(2)
    registry.initialize(nodes, edges)
    registry.apply(1, upsert_nodes=[{"id": "n00000", "locator": "confirmed.json"}])
    confirmed = registry.snapshot()
    receiver, sender = CONTEXT.Pipe(duplex=False)
    process = CONTEXT.Process(target=_kill_worker, args=(str(path), stage, sender))
    process.start()
    sender.close()
    try:
        marker = receive(receiver)
        if marker["pid"] != process.pid or marker["stage"] != stage:
            raise AssertionError("子进程停驻点不匹配")
        os.kill(process.pid, signal.SIGKILL)
        process.join(15)
        if process.is_alive() or process.exitcode != -signal.SIGKILL:
            raise AssertionError("没有发生预期的真实强杀")
        reopened = LogRegistry(path)
        recovery, error_name = None, None
        try:
            actual = reopened.snapshot()
        except UncommittedTailError as error:
            error_name = type(error).__name__
            recovery = reopened.recover_tail()
            actual = reopened.snapshot()
        expected = json.loads(json.dumps(confirmed))
        if stage == "after_head":
            expected["revision"] = 3
            expected["nodes"][0]["locator"] = "new-commit.json"
        expected_error = None if stage == "after_head" else "UncommittedTailError"
        continued = reopened.apply(actual["revision"])
        return {"stage": stage, "pid": process.pid, "signal": "SIGKILL", "exit_code": process.exitcode,
                "marker": marker, "confirmed_revision_before_kill": 2, "recovered_revision": actual["revision"],
                "read_error": error_name, "explicit_recovery": recovery, "continued_revision": continued,
                "passed": actual == expected and error_name == expected_error and continued == expected["revision"] + 1,
                "expected_sha256": fingerprint(expected), "actual_sha256": fingerprint(actual)}
    finally:
        cleanup_process(process)
        receiver.close()


def corruption_cases(directory):
    results = []
    for mode in ("committed_byte", "committed_truncation", "head", "snapshot"):
        path = Path(directory) / mode
        registry = LogRegistry(path)
        registry.initialize(*fixture(2))
        registry.apply(1, upsert_nodes=[{"id": "n00000", "locator": "confirmed.json"}])
        target = path / ("head.json" if mode == "head" else "snapshot.json" if mode == "snapshot" else "journal.log")
        content = target.read_bytes()
        if mode == "committed_truncation":
            target.write_bytes(content[:-8])
        else:
            target.write_bytes(b"!" + content[1:])
        corrupted = target.read_bytes()
        errors = []
        for action in (registry.snapshot, registry.recover_tail):
            try:
                action()
            except CorruptCommittedError as error:
                errors.append(type(error).__name__)
        results.append({"case": mode, "passed": len(errors) == 2 and target.read_bytes() == corrupted,
                        "read_and_recovery_errors": errors, "corruption_bytes_unchanged": target.read_bytes() == corrupted})
    return results


def expected_after_updates(size, root_index, updates):
    expected = expected_tree(size, root_index)
    expected["revision"] = updates + 1
    last_id = "n{:05d}".format(size - 1)
    for node in expected["nodes"]:
        if node["id"] == last_id:
            node["locator"] = "update-{:03d}.json".format(updates - 1)
    return expected


def workload(backend, path, size, updates, read_repetitions=5):
    registry = BACKENDS[backend](path)
    _, initialization = measured(lambda: registry.initialize(*fixture(size)))
    writes, reads = [], {"narrow": [], "full": []}
    initial_bytes = authority_bytes(backend, path)
    for index in range(updates):
        observation = {}
        previous_journal = (registry.path / "journal.log").stat().st_size if backend == "F-log" else None
        if backend == "S":
            original_connect = registry._connect
            def observed_commit(connection):
                wal = Path(str(registry.path) + "-wal")
                observation.update({"sql_rows_changed": connection.total_changes,
                                    "wal_bytes_after_commit": wal.stat().st_size if wal.exists() else 0})
            registry._connect = lambda *args, **kwargs: CommitProbe(original_connect(*args, **kwargs), after=observed_commit)
        try:
            revision, sample = measured(lambda: registry.apply(index + 1, upsert_nodes=[{
                "id": "n{:05d}".format(size - 1), "locator": "update-{:03d}.json".format(index)}]))
        finally:
            if backend == "S":
                registry._connect = original_connect
        sample.update({"index": index, "revision": revision, "correct": revision == index + 2})
        if backend == "F":
            sample["serialized_snapshot_bytes"] = Path(path).stat().st_size
        elif backend == "S":
            sample.update(observation)
        else:
            sample.update({"appended_record_bytes": (registry.path / "journal.log").stat().st_size - previous_journal,
                           "published_head_bytes": (registry.path / "head.json").stat().st_size})
        writes.append(sample)
    query = {"F": query_file, "S": query_sqlite, "F-log": query_log}[backend]
    expected = None
    for scope, root_index in (("narrow", max(0, (size - 2) // 4)), ("full", 0)):
        expected = expected_after_updates(size, root_index, updates)
        for repetition in range(read_repetitions):
            actual, sample = measured(lambda: query(path, "n{:05d}".format(root_index)))
            sample.update({"repetition": repetition, "correct": actual == expected,
                           "result_nodes": len(actual["nodes"]), "sha256": fingerprint(actual)})
            reads[scope].append(sample)
    registry.close()
    def reopen():
        instance = BACKENDS[backend](path)
        try:
            return instance.snapshot()
        finally:
            instance.close()
    actual, reopened = measured(reopen)
    reopened["correct"] = actual == expected
    result = {"initialization": initialization, "writes": writes, "reads": reads, "reopen": reopened,
              "initial_authority_bytes": initial_bytes, "final_authority_bytes": authority_bytes(backend, path),
              "passed": all(sample["correct"] for sample in writes) and reopened["correct"]
                        and all(sample["correct"] for samples in reads.values() for sample in samples)}
    if backend == "F-log":
        result["final_journal_bytes"] = (Path(path) / "journal.log").stat().st_size
    return result


def run(directory, repetitions=6):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    results = {"schema_version": 1, "captured_at_utc": datetime.now(timezone.utc).isoformat(), "fixture_root": str(directory),
               "environment": {"python": sys.version, "python_executable": sys.executable,
                               "platform": platform.platform(), "sqlite_version": sqlite3.sqlite_version},
               "repetitions": repetitions, "cas": log_cas(directory / "cas"), "kill_recovery": [], "cells": []}
    for stage in ("partial_record", "before_head", "after_head"):
        print("F-log 真实强杀：" + stage, flush=True)
        results["kill_recovery"].append(log_kill_recovery(directory / stage, stage))
    results["corruption"] = corruption_cases(directory / "corruption")
    for size in (1, 100, 1000):
        for profile, updates in (("read_mostly", 1), ("continuous_updates", 20)):
            print("工作负载：{} 节点 / {}".format(size, profile), flush=True)
            cells = {backend: {"backend": backend, "nodes": size, "profile": profile, "updates_per_round": updates,
                               "native_reads_per_round": 10, "rounds": []} for backend in BACKENDS}
            for repetition in range(repetitions):
                backends = list(BACKENDS)
                order = backends[repetition % 3:] + backends[:repetition % 3]
                for backend in order:
                    path = directory / "workloads" / ("{}-{}-{}-{}".format(size, profile, repetition, backend))
                    sample = workload(backend, path, size, updates)
                    sample.update({"repetition": repetition, "candidate_order": order})
                    cells[backend]["rounds"].append(sample)
            for cell in cells.values():
                cell["passed"] = all(sample["passed"] for sample in cell["rounds"])
                cell["summary"] = {
                    "write": summarize([sample for group in cell["rounds"] for sample in group["writes"]]),
                    "narrow": summarize([sample for group in cell["rounds"] for sample in group["reads"]["narrow"]]),
                    "full": summarize([sample for group in cell["rounds"] for sample in group["reads"]["full"]]),
                    "reopen": summarize([group["reopen"] for group in cell["rounds"]]),
                }
                results["cells"].append(cell)
    results["passed"] = results["cas"]["passed"] and all(item["passed"] for group in ("kill_recovery", "corruption", "cells") for item in results[group])
    root = Path(__file__).resolve().parent
    results["implementation_sha256"] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                        for name in ("log_store.py", "file_variant_benchmark.py", "file_store.py", "sqlite_store.py", "p2_local.py", "storage_common.py")}
    results["method"] = {
        "authority": "F-log 的 snapshot.json / journal.log / head.json 都是权威；日志不可作为缓存丢弃，无持久化索引或结果缓存",
        "durability": "F-log 先 fsync 追加日志，再 fsync 临时 head、原子替换和 fsync 目录；恢复仅隔离并截断提交水位之外的字节",
        "fairness": "相同图、相同变更与返回字段；每规模/工作负载至少 5 个独立实例轮次，轮换候选次序；每轮窄/全各 5 次读取；初始化单列",
        "read_scope": "F/S 复用原生读取适配器；F-log 每读需校验三份权威并重放日志；重开统一调用完整 Registry.snapshot",
        "resource_scope": "每个操作记录 CPU/进程累计 RSS/OS 计数；RSS 不是每请求净内存，OS 缓存未清；无 p95 或生产 SLO 声明",
        "bytes_scope": "记录应用序列化、日志或 WAL 字节，不代表 SSD 物理写入；F-log 另外重写小型提交水位",
    }
    results["not_validated"] = ["系统断电和设备缓存丢失", "多机器或网络文件系统", "日志压缩/轮换", "恶意重写权威及重算未加密校验", "产品集成"]
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="原始证据 JSON")
    parser.add_argument("--repetitions", type=int, default=6, help="每格独立轮次数，至少 5；默认 6 可完整轮换三候选")
    args = parser.parse_args()
    if args.repetitions < 5:
        parser.error("正式对照每格至少需要 5 个独立轮次")
    directory = Path(tempfile.mkdtemp(prefix="frontier-flog-", dir="/private/tmp"))
    results = run(directory, args.repetitions)
    results["command"] = [sys.executable] + sys.argv
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": results["passed"], "fixture_root": str(directory), "output": str(args.output)}, ensure_ascii=False))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
