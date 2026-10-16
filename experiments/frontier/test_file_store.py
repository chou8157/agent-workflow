"""真实文件与独立进程验证；不连接任何业务库。"""

import fcntl
import multiprocessing
import os
import stat
import time

import pytest

from experiments.frontier import file_store
from experiments.frontier.file_store import CommitUncertainError, FileRegistry
from experiments.frontier.storage_common import RevisionConflict


def nodes():
    return [{"id": "b", "locator": "b.json"}, {"id": "a", "locator": "a.json"}]


def edge(source="a", target="b", kind="contains"):
    return {"source": source, "target": target, "kind": kind}


def _competing_writer(path, start, results, identity):
    registry = FileRegistry(path)
    original = registry.snapshot()
    start.wait(timeout=10)
    try:
        revision = registry.apply(
            original["revision"], upsert_nodes=[{"id": identity, "locator": identity + ".json"}]
        )
        results.put(("committed", revision, identity))
    except RevisionConflict:
        results.put(("conflict", original["revision"], identity))
    finally:
        registry.close()


def _hold_lock(path, mode, ready, release):
    with open(path, "a+b") as stream:
        fcntl.flock(stream.fileno(), mode)
        ready.set()
        release.wait(timeout=10)


def test_normalized_snapshot_is_detached_and_persists_after_reopen(tmp_path):
    path = tmp_path / "nested" / "registry.json"
    registry = FileRegistry(path)
    initialized = registry.initialize(nodes(), [edge(kind="related"), edge()])
    assert initialized == {
        "revision": 1,
        "nodes": [{"id": "a", "locator": "a.json"}, {"id": "b", "locator": "b.json"}],
        "edges": [edge(), edge(kind="related")],
    }
    initialized["nodes"][0]["locator"] = "changed-outside.json"
    assert registry.snapshot()["nodes"][0]["locator"] == "a.json"
    assert registry.apply(1, upsert_nodes=[{"id": "a", "locator": "moved.json"}]) == 2
    registry.close()
    reopened = FileRegistry(path)
    assert reopened.snapshot()["revision"] == 2
    assert reopened.snapshot()["nodes"][0]["locator"] == "moved.json"


def test_initialize_does_not_overwrite_existing_authority(tmp_path):
    registry = FileRegistry(tmp_path / "registry.json")
    registry.initialize(nodes(), [edge()])
    original = registry.path.read_bytes()
    with pytest.raises(FileExistsError):
        registry.initialize([], [])
    assert registry.path.read_bytes() == original


def test_initialize_rejects_existing_broken_symlink(tmp_path):
    path = tmp_path / "registry.json"
    path.symlink_to(tmp_path / "missing.json")
    with pytest.raises(FileExistsError):
        FileRegistry(path).initialize([], [])
    assert path.is_symlink()


def test_stale_revision_cannot_overwrite_newer_data(tmp_path):
    registry = FileRegistry(tmp_path / "registry.json")
    registry.initialize(nodes(), [])
    old = registry.snapshot()
    registry.apply(old["revision"], add_edges=[edge()])
    committed = registry.path.read_bytes()
    with pytest.raises(RevisionConflict):
        registry.apply(old["revision"], upsert_nodes=[{"id": "a", "locator": "stale.json"}])
    assert registry.path.read_bytes() == committed
    assert registry.snapshot()["revision"] == 2


@pytest.mark.parametrize(
    "change",
    [
        {"add_edges": [edge(target="missing")]},
        {"add_edges": [edge()]},
        {"add_edges": [edge("b", "a")]},
        {"add_edges": [edge("a", "a")]},
        {"remove_nodes": ["b"]},
    ],
)
def test_invalid_mutation_preserves_original_bytes(tmp_path, change):
    registry = FileRegistry(tmp_path / "registry.json")
    registry.initialize(nodes(), [edge()])
    original = registry.path.read_bytes()
    with pytest.raises(ValueError):
        registry.apply(1, **change)
    assert registry.path.read_bytes() == original


def test_remove_edge_and_node_in_one_commit(tmp_path):
    registry = FileRegistry(tmp_path / "registry.json")
    registry.initialize(nodes(), [edge()])
    assert registry.apply(1, remove_edges=[edge()], remove_nodes=["b"]) == 2
    assert registry.snapshot() == {
        "revision": 2, "nodes": [{"id": "a", "locator": "a.json"}], "edges": []
    }


@pytest.mark.parametrize("contents", ["not-json", "[]", '{"revision":1,"nodes":[],"edges":[{}]}'])
def test_corrupt_authority_is_reported_not_replaced(tmp_path, contents):
    path = tmp_path / "registry.json"
    path.write_text(contents, encoding="utf-8")
    registry = FileRegistry(path)
    with pytest.raises(ValueError):
        registry.snapshot()
    with pytest.raises(ValueError):
        registry.apply(1)
    assert path.read_text(encoding="utf-8") == contents


def test_missing_authority_is_not_an_empty_registry(tmp_path):
    registry = FileRegistry(tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        registry.snapshot()
    assert not registry.path.exists()


def test_concurrent_processes_use_cas_inside_exclusive_lock(tmp_path):
    path = tmp_path / "registry.json"
    registry = FileRegistry(path)
    registry.initialize(nodes(), [])
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(4)
    results = context.Queue()
    processes = [
        context.Process(target=_competing_writer, args=(str(path), start, results, "writer-" + str(i)))
        for i in range(4)
    ]
    try:
        for process in processes:
            process.start()
        outcomes = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert sorted(result[0] for result in outcomes) == ["committed", "conflict", "conflict", "conflict"]
        winner = next(result[2] for result in outcomes if result[0] == "committed")
        snapshot = registry.snapshot()
        assert snapshot["revision"] == 2
        assert {node["id"] for node in snapshot["nodes"]} == {"a", "b", winner}
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
        results.close()
        results.join_thread()


@pytest.mark.parametrize("lock_mode, can_read", [(fcntl.LOCK_SH, True), (fcntl.LOCK_EX, False)])
def test_lock_timeout_and_shared_reader_behavior(tmp_path, lock_mode, can_read):
    registry = FileRegistry(tmp_path / "registry.json", lock_timeout=0.1)
    registry.initialize(nodes(), [])
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_lock, args=(str(registry.lock_path), lock_mode, ready, release))
    process.start()
    try:
        assert ready.wait(timeout=10)
        if can_read:
            assert registry.snapshot()["revision"] == 1
        else:
            with pytest.raises(TimeoutError):
                registry.snapshot()
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            registry.apply(1, add_edges=[edge()])
        assert time.monotonic() - started < 2
    finally:
        release.set()
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0
    assert registry.snapshot()["revision"] == 1
    assert registry.apply(1, add_edges=[edge()]) == 2


@pytest.mark.parametrize("failure", ["replace", "file_fsync"])
def test_failure_before_replace_keeps_old_authority_and_cleans_temp(tmp_path, monkeypatch, failure):
    registry = FileRegistry(tmp_path / "registry.json")
    registry.initialize(nodes(), [])
    original = registry.path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("模拟原子替换前故障")

    monkeypatch.setattr(file_store.os, "replace" if failure == "replace" else "fsync", fail)
    with pytest.raises(OSError, match="模拟原子替换前故障"):
        registry.apply(1, add_edges=[edge()])
    assert registry.path.read_bytes() == original
    assert list(tmp_path.glob(".registry.json.*.tmp")) == []
    assert registry.snapshot()["revision"] == 1


def test_directory_fsync_failure_reports_uncertain_commit_and_requires_reread(tmp_path, monkeypatch):
    registry = FileRegistry(tmp_path / "registry.json")
    registry.initialize(nodes(), [])
    real_fsync = os.fsync

    def fail_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("模拟目录持久化确认失败")
        real_fsync(descriptor)

    monkeypatch.setattr(file_store.os, "fsync", fail_directory)
    with pytest.raises(CommitUncertainError, match="禁止自动重试"):
        registry.apply(1, add_edges=[edge()])
    current = FileRegistry(registry.path).snapshot()
    assert current["revision"] == 2
    assert current["edges"] == [edge()]
    with pytest.raises(RevisionConflict):
        registry.apply(1, add_edges=[edge()])
    assert list(tmp_path.glob(".registry.json.*.tmp")) == []


def test_closed_registry_rejects_operations(tmp_path):
    registry = FileRegistry(tmp_path / "registry.json")
    registry.close()
    registry.close()
    for operation in (lambda: registry.initialize([], []), registry.snapshot, lambda: registry.apply(1)):
        with pytest.raises(ValueError, match="已关闭"):
            operation()
    assert not registry.path.exists()


def test_invalid_initial_data_does_not_create_authority(tmp_path):
    registry = FileRegistry(tmp_path / "registry.json")
    with pytest.raises(ValueError):
        registry.initialize(nodes(), [edge("a", "a")])
    assert not registry.path.exists()


def test_contains_dag_allows_multiple_parents_and_related_cycles(tmp_path):
    registry = FileRegistry(tmp_path / "registry.json")
    registry.initialize(nodes() + [{"id": "c", "locator": "c.json"}], [edge(), edge("c", "b")])
    registry.apply(1, add_edges=[edge("b", "a", "related"), edge("a", "b", "related")])
    assert len(registry.snapshot()["edges"]) == 4
