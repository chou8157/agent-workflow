"""F-log 合约与崩溃边界；预期快照独立构造。"""

import hashlib
import json

import pytest

from experiments.frontier.log_store import LogRegistry, UncommittedTailError, CorruptCommittedError, CommitUncertainError, envelope
from experiments.frontier.storage_common import RevisionConflict
from experiments.frontier.file_variant_benchmark import log_cas, log_kill_recovery, corruption_cases, query_log, workload


NODES = [{"id": "a", "locator": "a.json"}, {"id": "b", "locator": "b.json"}]
EDGE = {"source": "a", "target": "b", "kind": "contains"}


def test_initialize_reopen_and_missing_authority(tmp_path):
    path = tmp_path / "registry"
    registry = LogRegistry(path)
    with pytest.raises(FileNotFoundError):
        registry.snapshot()
    assert not path.exists()
    registry.initialize(NODES, [EDGE])
    assert registry.apply(1, upsert_nodes=[{"id": "b", "locator": "moved.json"}]) == 2
    registry.close()
    assert LogRegistry(path).snapshot() == {"revision": 2, "nodes": [NODES[0], {"id": "b", "locator": "moved.json"}], "edges": [EDGE]}
    with pytest.raises(FileExistsError):
        LogRegistry(path).initialize([], [])


@pytest.mark.parametrize("operation", [
    {"add_edges": [{"source": "b", "target": "a", "kind": "contains"}]},
    {"add_edges": [{"source": "a", "target": "missing", "kind": "contains"}]},
    {"remove_nodes": ["b"]}, {"add_edges": [EDGE]},
])
def test_invalid_mutation_never_appends_or_advances_watermark(tmp_path, operation):
    registry = LogRegistry(tmp_path / "registry")
    registry.initialize(NODES, [EDGE])
    before = {name: (registry.path / name).read_bytes() for name in ("snapshot.json", "journal.log", "head.json")}
    with pytest.raises(ValueError):
        registry.apply(1, **operation)
    assert before == {name: (registry.path / name).read_bytes() for name in before}


def test_stale_revision_and_edge_removal(tmp_path):
    registry = LogRegistry(tmp_path / "registry")
    registry.initialize(NODES, [EDGE])
    assert registry.apply(1, remove_edges=[EDGE], remove_nodes=["b"]) == 2
    with pytest.raises(RevisionConflict):
        registry.apply(1)
    assert registry.snapshot() == {"revision": 2, "nodes": [NODES[0]], "edges": []}


def test_partial_tail_is_reported_and_explicit_recovery_preserves_confirmed_commit(tmp_path):
    registry = LogRegistry(tmp_path / "registry")
    registry.initialize(NODES, [EDGE])
    registry.apply(1, upsert_nodes=[{"id": "a", "locator": "confirmed.json"}])
    confirmed = registry.snapshot()
    tail = b'{"payload":{"revision":3'
    with (registry.path / "journal.log").open("ab") as stream:
        stream.write(tail)
    with pytest.raises(UncommittedTailError):
        registry.snapshot()
    with pytest.raises(UncommittedTailError):
        registry.apply(2)
    recovery = registry.recover_tail()
    assert recovery["revision"] == 2 and recovery["removed_uncommitted_bytes"] == len(tail)
    assert recovery["tail_sha256"] == hashlib.sha256(tail).hexdigest()
    assert registry.snapshot() == confirmed
    assert registry.recover_tail()["removed_uncommitted_bytes"] == 0


def test_committed_corruption_and_missing_authority_components_fail_closed(tmp_path):
    assert all(case["passed"] for case in corruption_cases(tmp_path / "corruption"))
    registry = LogRegistry(tmp_path / "missing-component")
    registry.initialize(NODES, [EDGE])
    (registry.path / "journal.log").unlink()
    with pytest.raises(CorruptCommittedError):
        registry.snapshot()


def test_checksum_valid_but_invalid_head_shape_is_rejected(tmp_path):
    registry = LogRegistry(tmp_path / "registry")
    registry.initialize(NODES, [EDGE])
    (registry.path / "head.json").write_text(json.dumps(envelope([])), encoding="utf-8")
    with pytest.raises(CorruptCommittedError):
        registry.snapshot()
    with pytest.raises(CorruptCommittedError):
        registry.recover_tail()


def test_directory_sync_failure_reports_uncertain_commit_and_requires_reread(tmp_path, monkeypatch):
    registry = LogRegistry(tmp_path / "registry")
    registry.initialize(NODES, [EDGE])
    def failed_sync():
        raise OSError("模拟目录 fsync 失败")
    monkeypatch.setattr(registry, "_sync_directory", failed_sync)
    with pytest.raises(CommitUncertainError):
        registry.apply(1, upsert_nodes=[{"id": "a", "locator": "published.json"}])
    assert LogRegistry(registry.path).snapshot()["revision"] == 2
    with pytest.raises(RevisionConflict):
        LogRegistry(registry.path).apply(1)


def test_sixteen_process_cas_has_exactly_one_winner(tmp_path):
    result = log_cas(tmp_path / "cas")
    assert result["passed"]
    assert sum(item["status"] == "committed" for item in result["outcomes"]) == 1
    assert sum(item["status"] == "conflict" for item in result["outcomes"]) == 15


@pytest.mark.parametrize("stage,revision,error", [
    ("partial_record", 2, "UncommittedTailError"),
    ("before_head", 2, "UncommittedTailError"),
    ("after_head", 3, None),
])
def test_actual_sigkill_never_discards_previously_confirmed_revision(tmp_path, stage, revision, error):
    result = log_kill_recovery(tmp_path / stage, stage)
    assert result["passed"] and result["exit_code"] == -9
    assert result["recovered_revision"] == revision and result["read_error"] == error


def test_local_query_includes_self_and_deduplicates_diamond(tmp_path):
    registry = LogRegistry(tmp_path / "registry")
    nodes = [{"id": name, "locator": name + ".json"} for name in ("a", "b", "c", "d", "outside")]
    edges = [{"source": source, "target": target, "kind": "contains"}
             for source, target in (("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"))]
    registry.initialize(nodes, edges + [{"source": "a", "target": "outside", "kind": "related"}])
    assert query_log(registry.path, "a") == {"revision": 1, "nodes": nodes[:4], "edges": edges}
    assert query_log(registry.path, "d") == {"revision": 1, "nodes": [nodes[3]], "edges": []}


@pytest.mark.parametrize("backend", ["F", "S", "F-log"])
def test_common_workload_uses_independent_expected_state(tmp_path, backend):
    result = workload(backend, tmp_path / backend, size=10, updates=3, read_repetitions=1)
    assert result["passed"]
    assert [sample["revision"] for sample in result["writes"]] == [2, 3, 4]
