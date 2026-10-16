"""P2 实验预期由字面量与独立编号 oracle 给出，真实强杀仅作用于自己的子进程。"""

import signal

import pytest

from experiments.frontier import p2_local


@pytest.mark.parametrize("backend", ["F", "S"])
def test_sixteen_process_cas_has_one_winner(tmp_path, backend):
    result = p2_local.cas_competition(backend, tmp_path / ("authority" + p2_local.SUFFIXES[backend]), writers=16)
    assert result["passed"]
    assert len({item["pid"] for item in result["outcomes"]}) == 16
    assert sum(item["status"] == "committed" for item in result["outcomes"]) == 1
    assert sum(item["status"] == "conflict" for item in result["outcomes"]) == 15


@pytest.mark.parametrize("backend", ["F", "S"])
@pytest.mark.parametrize("stage,revision", [("before_commit", 1), ("after_commit", 2)])
def test_real_sigkill_preserves_the_expected_commit_boundary(tmp_path, backend, stage, revision):
    result = p2_local.kill_recovery(backend, tmp_path / ("authority" + p2_local.SUFFIXES[backend]), stage)
    assert result["signal"] == "SIGKILL"
    assert result["exit_code"] == -signal.SIGKILL
    assert result["recovered_revision"] == revision
    assert result["continued_revision"] == revision + 1
    assert result["passed"]


@pytest.mark.parametrize("backend", ["F", "S"])
def test_backup_during_writes_is_consistent_and_restorable(tmp_path, backend):
    result = p2_local.concurrent_backups(backend, tmp_path, count=3, updates=10)
    assert result["passed"]
    assert result["final_revision"] == 11
    assert any(result["overlaps_writer_interval"])


@pytest.mark.parametrize("backend", ["F", "S"])
def test_logical_migration_roundtrip_preserves_revision_and_source(tmp_path, backend):
    result = p2_local.migration_roundtrip(backend, tmp_path)
    assert result["passed"]
    assert result["revision"] == 5
    assert result["source_sha256"] == result["middle_sha256"] == result["returned_sha256"]


@pytest.mark.parametrize("backend,query", [("F", p2_local.query_file), ("S", p2_local.query_sqlite)])
def test_native_query_deduplicates_diamond_and_ignores_related_expansion(tmp_path, backend, query):
    path = tmp_path / ("authority" + p2_local.SUFFIXES[backend])
    nodes = [{"id": name, "locator": name + ".json"} for name in ("a", "b", "c", "d", "outside")]
    edges = [
        {"source": "a", "target": "b", "kind": "contains"},
        {"source": "a", "target": "c", "kind": "contains"},
        {"source": "b", "target": "d", "kind": "contains"},
        {"source": "c", "target": "d", "kind": "contains"},
        {"source": "a", "target": "outside", "kind": "related"},
    ]
    p2_local.BACKENDS[backend](path).initialize(nodes, edges)
    result = query(path, "a")
    assert result == {"revision": 1, "nodes": nodes[:4], "edges": edges[:4]}
    assert query(path, "d") == {"revision": 1, "nodes": [nodes[3]], "edges": []}
    with pytest.raises(ValueError, match="根节点不存在"):
        query(path, "missing")


def test_numbered_oracle_has_independent_known_expectations():
    result = p2_local.expected_tree(10, 1)
    assert [node["id"] for node in result["nodes"]] == ["n00001", "n00005", "n00006", "n00007", "n00008"]
    assert [(edge["source"], edge["target"]) for edge in result["edges"]] == [
        ("n00001", "n00005"), ("n00001", "n00006"), ("n00001", "n00007"), ("n00001", "n00008")]


def test_offline_import_does_not_overwrite_existing_authority(tmp_path):
    destination = tmp_path / "existing.json"
    destination.write_bytes(b"preserve existing data")
    with pytest.raises(FileExistsError):
        p2_local.import_snapshot("F", destination, {"revision": 7, "nodes": [], "edges": []})
    assert destination.read_bytes() == b"preserve existing data"
