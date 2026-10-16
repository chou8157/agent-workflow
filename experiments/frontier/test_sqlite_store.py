"""SQLite 原型的事务、约束和多进程回归验证。"""

import multiprocessing
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlite_store import SQLiteRegistry
from storage_common import RevisionConflict


NODES = [{"id": "b", "locator": "b.json"}, {"id": "a", "locator": "a.json"}]
EDGE = {"source": "a", "target": "b", "kind": "contains"}


def _compete(path, ready, start, results, index):
    registry = SQLiteRegistry(path)
    ready.put(index)
    if not start.wait(15):
        results.put(("error", "未收到并发启动信号"))
        return
    try:
        result = registry.apply(1, upsert_nodes=[{"id": "writer-{}".format(index), "locator": "new.json"}])
        results.put(("success", result))
    except RevisionConflict:
        results.put(("conflict", index))
    except Exception as error:
        results.put(("error", repr(error)))
    finally:
        registry.close()


def test_initialize_snapshot_and_reopen_preserve_authority(tmp_path):
    path = tmp_path / "registry.sqlite"
    registry = SQLiteRegistry(path)
    assert not path.exists()
    registry.initialize(NODES, [EDGE])
    assert registry.snapshot() == {"revision": 1, "nodes": sorted(NODES, key=lambda node: node["id"]), "edges": [EDGE]}
    assert registry.apply(1, upsert_nodes=[{"id": "b", "locator": "moved.json"}]) == 2
    snapshot = registry.snapshot()
    registry.close()
    reopened = SQLiteRegistry(path)
    assert reopened.snapshot() == snapshot
    assert snapshot["nodes"][1]["locator"] == "moved.json"
    with pytest.raises(ValueError, match="拒绝覆盖"):
        reopened.initialize([], [])
    assert reopened.snapshot() == snapshot
    reopened.close()


def test_missing_or_empty_authority_is_not_silently_created(tmp_path):
    path = tmp_path / "missing" / "registry.sqlite"
    registry = SQLiteRegistry(path)
    with pytest.raises(FileNotFoundError):
        registry.snapshot()
    with pytest.raises(FileNotFoundError):
        registry.apply(1)
    assert not path.parent.exists()
    path.parent.mkdir()
    path.write_bytes(b"")
    with pytest.raises(ValueError):
        registry.snapshot()
    with pytest.raises(ValueError, match="拒绝覆盖"):
        registry.initialize([], [])
    assert path.read_bytes() == b""


def test_corrupted_authority_fails_explicitly(tmp_path):
    path = tmp_path / "corrupt.sqlite"
    content = b"not a sqlite authority"
    path.write_bytes(content)
    registry = SQLiteRegistry(path)
    with pytest.raises(ValueError, match="读取失败"):
        registry.snapshot()
    assert path.read_bytes() == content


def test_stale_revision_does_not_write(tmp_path):
    registry = SQLiteRegistry(tmp_path / "registry.sqlite")
    registry.initialize(NODES, [EDGE])
    assert registry.apply(1) == 2
    before = registry.snapshot()
    with pytest.raises(RevisionConflict):
        registry.apply(1, upsert_nodes=[{"id": "a", "locator": "wrong.json"}])
    assert registry.snapshot() == before


@pytest.mark.parametrize("operation", [
    {"add_edges": [{"source": "b", "target": "a", "kind": "contains"}]},
    {"add_edges": [{"source": "a", "target": "absent", "kind": "contains"}]},
    {"remove_nodes": ["b"]},
    {"add_edges": [EDGE]},
])
def test_invalid_graph_rolls_back_all_changes(tmp_path, operation):
    registry = SQLiteRegistry(tmp_path / "registry.sqlite")
    registry.initialize(NODES, [EDGE])
    before = registry.snapshot()
    with pytest.raises(ValueError):
        registry.apply(1, upsert_nodes=[{"id": "a", "locator": "must-not-persist.json"}], **operation)
    assert registry.snapshot() == before


def test_edge_and_node_removal_are_atomic_and_related_cycles_are_allowed(tmp_path):
    registry = SQLiteRegistry(tmp_path / "registry.sqlite")
    registry.initialize(NODES, [EDGE])
    assert registry.apply(1, add_edges=[{"source": "b", "target": "a", "kind": "related"}]) == 2
    assert registry.apply(2, remove_nodes=["b"], remove_edges=[EDGE, {"source": "b", "target": "a", "kind": "related"}]) == 3
    assert registry.snapshot() == {"revision": 3, "nodes": [{"id": "a", "locator": "a.json"}], "edges": []}


def test_database_constraints_and_wal_are_real(tmp_path):
    path = tmp_path / "registry.sqlite"
    registry = SQLiteRegistry(path)
    registry.initialize(NODES, [EDGE])
    with sqlite3.connect(str(path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"meta", "nodes", "edges"}
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO edges VALUES ('a','absent','contains')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO edges VALUES ('a','b','contains')")


def test_database_failure_after_sql_mutation_rolls_back(tmp_path):
    path = tmp_path / "registry.sqlite"
    registry = SQLiteRegistry(path)
    registry.initialize(NODES, [EDGE])
    before = registry.snapshot()
    with sqlite3.connect(str(path)) as connection:
        connection.execute("CREATE TRIGGER reject_revision BEFORE UPDATE ON meta BEGIN SELECT RAISE(ABORT, '模拟写入故障'); END")
    with pytest.raises(ValueError, match="更新失败"):
        registry.apply(1, upsert_nodes=[{"id": "a", "locator": "must-rollback.json"}])
    assert registry.snapshot() == before


def test_multiple_processes_have_one_cas_winner(tmp_path):
    path = tmp_path / "registry.sqlite"
    registry = SQLiteRegistry(path)
    registry.initialize(NODES, [EDGE])
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(target=_compete, args=(str(path), ready, start, results, index)) for index in range(4)]
    try:
        for process in processes:
            process.start()
        assert {ready.get(timeout=15) for _ in processes} == set(range(4))
        start.set()
        outcomes = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        assert sorted(result[0] for result in outcomes) == ["conflict", "conflict", "conflict", "success"]
        assert registry.snapshot()["revision"] == 2
        assert len(registry.snapshot()["nodes"]) == 3
    finally:
        start.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
        ready.close()
        results.close()


def test_concurrent_readers_observe_consistent_revision_and_nodes(tmp_path):
    path = tmp_path / "registry.sqlite"
    registry = SQLiteRegistry(path)
    registry.initialize([{"id": "a", "locator": "1"}], [])

    def writer():
        instance = SQLiteRegistry(path)
        for revision in range(1, 31):
            assert instance.apply(revision, upsert_nodes=[{"id": "a", "locator": str(revision + 1)}]) == revision + 1

    def reader():
        instance = SQLiteRegistry(path)
        for _ in range(40):
            snapshot = instance.snapshot()
            assert snapshot["nodes"][0]["locator"] == str(snapshot["revision"])

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(writer), executor.submit(reader), executor.submit(reader)]
        for future in futures:
            future.result(timeout=20)
    assert registry.snapshot()["revision"] == 31
