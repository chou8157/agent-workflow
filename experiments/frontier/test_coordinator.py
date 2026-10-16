from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))

import coordinator
from coordinator import QueryError, paginate, query


START = "2026-10-05T00:00:00+08:00"
END = "2026-10-12T00:00:00+08:00"
WHEN = "2026-10-07T12:00:00+08:00"


@pytest.fixture(params=["central", "hierarchical"])
def strategy(request):
    return request.param


def record(record_id, value=None, revision=1, occurred_at=WHEN):
    return {
        "record_id": record_id,
        "revision": revision,
        "occurred_at": occurred_at,
        "value": {"title": "same", "requirement": "R-1"} if value is None else value,
    }


def source(source_root, node_id, facts, view_id="main"):
    source_root.mkdir(parents=True, exist_ok=True)
    path = source_root / (node_id + ".json")
    path.write_text(
        json.dumps({"node_id": node_id, "view_id": view_id, "facts": facts}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"id": node_id, "locator": str(path.resolve())}


def snapshot(nodes, contains=(), related=()):
    return {
        "revision": 7,
        "nodes": nodes,
        "edges": [
            {"source": parent, "target": child, "kind": "contains"}
            for parent, child in contains
        ] + [
            {"source": parent, "target": child, "kind": "related"}
            for parent, child in related
        ],
    }


def run_query(state, source_root, strategy, **kwargs):
    return query(state, "A", source_root, START, END, strategy=strategy, **kwargs)


def facts_by_identity(result):
    facts = result["facts"]
    found = {(fact["origin_node_id"], fact["record_id"]): fact for fact in facts}
    assert len(found) == len(facts), "duplicate fact identity"
    return found


def assert_coverage(result, expected, succeeded, failed=(), skipped=()):
    coverage = result["coverage"]
    assert set(coverage["expected"]) == set(expected)
    assert len(coverage["expected"]) == len(set(expected))
    assert set(coverage["succeeded"]) == set(succeeded)
    assert len(coverage["succeeded"]) == len(set(succeeded))
    assert set(coverage["failed"]) == set(failed)
    assert set(coverage["skipped"]) == set(skipped)
    assert set(coverage["visited"]) == set(succeeded) | set(failed)
    assert len(coverage["visited"]) == len(set(succeeded) | set(failed))
    assert set(expected) == set(succeeded) | set(failed) | set(skipped)
    assert not (set(succeeded) & set(failed) or set(succeeded) & set(skipped) or set(failed) & set(skipped))
    assert all(coverage["failed"].values())
    assert all(coverage["skipped"].values())


def assert_evidence(result, nodes):
    paths = {node["id"]: Path(node["locator"]) for node in nodes}
    for fact in result["facts"]:
        path = paths[fact["origin_node_id"]]
        expected = (str(path), hashlib.sha256(path.read_bytes()).hexdigest())
        assert fact["sources"]
        assert {(item["path"], item["sha256"]) for item in fact["sources"]} == {expected}


@pytest.mark.parametrize("shape", ["flat", "nested", "multiparent"])
def test_fixed_identity_oracle_is_invariant_across_topologies(tmp_path, strategy, shape):
    nodes = [source(tmp_path, node, [record("same-id")]) for node in ["A", "B", "C", "D"]]
    edges = {
        "flat": [("A", "B"), ("A", "C"), ("A", "D")],
        "nested": [("A", "B"), ("B", "C"), ("C", "D")],
        "multiparent": [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
    }[shape]
    state = snapshot(nodes, edges)
    state_before = copy.deepcopy(state)
    source_before = {node["locator"]: Path(node["locator"]).read_bytes() for node in nodes}

    result = run_query(state, tmp_path, strategy)

    assert result["status"] == "full"
    assert result["registry_revision"] == 7
    assert result["conflicts"] == []
    assert_coverage(result, {"A", "B", "C", "D"}, {"A", "B", "C", "D"})
    assert set(facts_by_identity(result)) == {("A", "same-id"), ("B", "same-id"), ("C", "same-id"), ("D", "same-id")}
    for fact in result["facts"]:
        assert fact["value"] == {"title": "same", "requirement": "R-1"}
        assert fact["revision"] == 1
        assert datetime.fromisoformat(fact["occurred_at"]) == datetime.fromisoformat(WHEN)
    assert_evidence(result, nodes)
    assert state == state_before
    assert source_before == {node["locator"]: Path(node["locator"]).read_bytes() for node in nodes}


def test_input_order_does_not_change_fixed_result(tmp_path, strategy):
    nodes = [source(tmp_path, node, [record("own")]) for node in ["A", "B", "C", "D"]]
    state = snapshot(list(reversed(nodes)), [("C", "D"), ("B", "D"), ("A", "C"), ("A", "B")])
    result = run_query(state, tmp_path, strategy)
    assert result["status"] == "full"
    assert set(facts_by_identity(result)) == {("A", "own"), ("B", "own"), ("C", "own"), ("D", "own")}
    assert_coverage(result, {"A", "B", "C", "D"}, {"A", "B", "C", "D"})


def test_related_edge_does_not_extend_subtree_or_read_unrelated_source(tmp_path, strategy):
    nodes = [source(tmp_path, node, [record("own")]) for node in ["A", "B"]]
    nodes += [{"id": "X", "locator": str(tmp_path / "missing-X.json")}, {"id": "Y", "locator": str(tmp_path / "missing-Y.json")}]
    result = run_query(snapshot(nodes, [("A", "B"), ("X", "Y")], [("A", "X")]), tmp_path, strategy)
    assert result["status"] == "full"
    assert set(facts_by_identity(result)) == {("A", "own"), ("B", "own")}
    assert_coverage(result, {"A", "B"}, {"A", "B"})


def test_half_open_week_uses_instants_across_timezones(tmp_path, strategy):
    facts = [
        record("before", occurred_at="2026-10-04T15:59:59+00:00"),
        record("start", occurred_at="2026-10-04T16:00:00+00:00"),
        record("near-end", occurred_at="2026-10-11T23:59:59+08:00"),
        record("end", occurred_at="2026-10-11T16:00:00+00:00"),
        record("after", occurred_at="2026-10-12T00:00:01+08:00"),
    ]
    result = run_query(snapshot([source(tmp_path, "A", facts)]), tmp_path, strategy)
    assert result["status"] == "full"
    assert set(facts_by_identity(result)) == {("A", "start"), ("A", "near-end")}
    assert_coverage(result, {"A"}, {"A"})


@pytest.mark.parametrize("facts", [[], [record("old", occurred_at="2026-10-01T00:00:00+08:00")]])
def test_zero_activity_is_successful_and_full(tmp_path, strategy, facts):
    result = run_query(snapshot([source(tmp_path, "A", facts)]), tmp_path, strategy)
    assert result["status"] == "full"
    assert result["facts"] == []
    assert result["conflicts"] == []
    assert_coverage(result, {"A"}, {"A"})


@pytest.mark.parametrize("failure", ["missing", "malformed", "identity", "view"])
def test_bad_source_is_partial_and_cannot_shrink_expected_coverage(tmp_path, strategy, failure):
    a = source(tmp_path, "A", [record("own")])
    b = source(tmp_path, "B", [record("hidden")])
    path = Path(b["locator"])
    if failure == "missing":
        path.unlink()
    elif failure == "malformed":
        path.write_text("{", encoding="utf-8")
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["node_id" if failure == "identity" else "view_id"] = "other"
        path.write_text(json.dumps(payload), encoding="utf-8")
    result = run_query(snapshot([a, b], [("A", "B")]), tmp_path, strategy)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("A", "own")}
    assert_coverage(result, {"A", "B"}, {"A"}, failed={"B"})


def test_unreachable_and_empty_are_not_the_same(tmp_path, strategy):
    nodes = [source(tmp_path, "A", []), source(tmp_path, "B", [])]
    nodes += [{"id": "D", "locator": str(tmp_path / "offline.json")}]
    result = run_query(snapshot(nodes, [("A", "B"), ("A", "D")]), tmp_path, strategy)
    assert result["status"] == "partial"
    assert result["facts"] == []
    assert_coverage(result, {"A", "B", "D"}, {"A", "B"}, failed={"D"})


def test_explicit_denial_remains_a_coverage_gap(tmp_path, strategy):
    nodes = [source(tmp_path, node, [record("own")]) for node in ["A", "B"]]
    result = run_query(snapshot(nodes, [("A", "B")]), tmp_path, strategy, denied={"B"})
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("A", "own")}
    assert_coverage(result, {"A", "B"}, {"A"}, failed={"B"})


@pytest.mark.parametrize("escape", ["absolute", "symlink"])
def test_source_root_escape_is_rejected(tmp_path, strategy, escape):
    root = tmp_path / "sources"
    a = source(root, "A", [record("own")])
    b = source(tmp_path / "outside", "B", [record("secret")])
    if escape == "symlink":
        link = root / "linked.json"
        link.symlink_to(b["locator"])
        b["locator"] = str(link)
    result = run_query(snapshot([a, b], [("A", "B")]), root, strategy)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("A", "own")}
    assert_coverage(result, {"A", "B"}, {"A"}, failed={"B"})


def force_darwin_fallback(monkeypatch):
    if sys.platform != "darwin":
        pytest.skip("Darwin fallback requires macOS")
    monkeypatch.setattr(coordinator.os, "supports_dir_fd", set())


@pytest.mark.parametrize("force_fallback", [False, True])
def test_file_symlink_swap_after_authorization_cannot_escape_source_root(tmp_path, strategy, monkeypatch, force_fallback):
    if force_fallback:
        force_darwin_fallback(monkeypatch)
    root = tmp_path / "sources"
    node = source(root, "A", [record("allowed")])
    external = source(tmp_path / "outside", "A", [record("secret", {"state": "outside"})])
    path = Path(node["locator"])
    original_read = coordinator._read_bytes
    swapped = []

    def replace_file_before_open(requested_path):
        if Path(requested_path) == path and not swapped:
            path.rename(path.with_name("A.original.json"))
            path.symlink_to(external["locator"])
            swapped.append(True)
        return original_read(requested_path)

    monkeypatch.setattr(coordinator, "_read_bytes", replace_file_before_open)
    result = run_query(snapshot([node]), root, strategy)
    assert swapped == [True]
    assert path.is_symlink()
    assert result["status"] == "partial"
    assert result["facts"] == []
    assert_coverage(result, {"A"}, set(), failed={"A"})
    assert result["metrics"]["source_bytes_read"] == 0
    assert result["metrics"]["source_read_attempts"] == 1


@pytest.mark.parametrize("force_fallback", [False, True])
def test_parent_directory_symlink_swap_after_authorization_cannot_escape_source_root(tmp_path, strategy, monkeypatch, force_fallback):
    if force_fallback:
        force_darwin_fallback(monkeypatch)
    root = tmp_path / "sources"
    node = source(root / "branch", "A", [record("allowed")])
    external = source(tmp_path / "outside", "A", [record("secret", {"state": "outside"})])
    path = Path(node["locator"])
    directory = path.parent
    original_read = coordinator._read_bytes
    swapped = []

    def replace_directory_before_open(requested_path):
        if Path(requested_path) == path and not swapped:
            directory.rename(directory.with_name("branch-original"))
            directory.symlink_to(Path(external["locator"]).parent, target_is_directory=True)
            swapped.append(True)
        return original_read(requested_path)

    monkeypatch.setattr(coordinator, "_read_bytes", replace_directory_before_open)
    result = run_query(snapshot([node]), root, strategy)
    assert swapped == [True]
    assert directory.is_symlink()
    assert result["status"] == "partial"
    assert result["facts"] == []
    assert_coverage(result, {"A"}, set(), failed={"A"})
    assert result["metrics"]["source_bytes_read"] == 0
    assert result["metrics"]["source_read_attempts"] == 1


def test_no_dir_fd_explicitly_exercises_darwin_fallback(tmp_path, strategy, monkeypatch):
    force_darwin_fallback(monkeypatch)
    node = source(tmp_path, "A", [record("own")])
    expected_bytes = 2 * len(Path(node["locator"]).read_bytes())
    original_fallback = coordinator._read_bytes_darwin
    fallback_calls = []

    def record_fallback(requested_path):
        fallback_calls.append(str(requested_path))
        return original_fallback(requested_path)

    monkeypatch.setattr(coordinator, "_read_bytes_darwin", record_fallback)
    result = run_query(snapshot([node]), tmp_path, strategy)
    assert fallback_calls == [node["locator"], node["locator"]]
    assert result["status"] == "full"
    assert set(facts_by_identity(result)) == {("A", "own")}
    assert_coverage(result, {"A"}, {"A"})
    assert result["metrics"]["source_bytes_read"] == expected_bytes
    assert result["metrics"]["source_read_attempts"] == 2


def test_unknown_platform_without_dir_fd_rejects_before_opening_content(tmp_path, strategy, monkeypatch):
    node = source(tmp_path, "A", [record("secret")])
    attempted_opens = []

    def unexpected_open(*args, **kwargs):
        attempted_opens.append((args, kwargs))
        raise AssertionError("unsupported platform attempted to open source")

    monkeypatch.setattr(coordinator.os, "supports_dir_fd", set())
    monkeypatch.setattr(coordinator.sys, "platform", "unsupported-test-platform")
    monkeypatch.setattr(coordinator.os, "open", unexpected_open)
    result = run_query(snapshot([node]), tmp_path, strategy)
    assert attempted_opens == []
    assert result["status"] == "partial"
    assert result["facts"] == []
    assert_coverage(result, {"A"}, set(), failed={"A"})
    assert "dir_fd" in result["coverage"]["failed"]["A"]
    assert result["metrics"]["source_bytes_read"] == 0
    assert result["metrics"]["source_read_attempts"] == 1


def test_darwin_post_read_path_change_keeps_actual_byte_count(tmp_path, strategy, monkeypatch):
    force_darwin_fallback(monkeypatch)
    root = tmp_path / "sources"
    node = source(root / "branch", "A", [record("own")])
    path = Path(node["locator"])
    expected_bytes = len(path.read_bytes())
    original_fdopen = coordinator.os.fdopen
    actual_read_sizes = []

    class RenameAfterRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, *args, **kwargs):
            data = self.stream.read(*args, **kwargs)
            actual_read_sizes.append(len(data))
            path.parent.rename(path.parent.with_name("renamed-after-read"))
            return data

    def instrument_fdopen(*args, **kwargs):
        return RenameAfterRead(original_fdopen(*args, **kwargs))

    monkeypatch.setattr(coordinator.os, "fdopen", instrument_fdopen)
    result = run_query(snapshot([node]), root, strategy)
    assert actual_read_sizes == [expected_bytes]
    assert result["status"] == "partial"
    assert result["facts"] == []
    assert_coverage(result, {"A"}, set(), failed={"A"})
    assert result["metrics"]["source_bytes_read"] == expected_bytes
    assert result["metrics"]["source_read_attempts"] == 1


def test_successful_read_metrics_include_both_source_reads(tmp_path, strategy):
    nodes = [source(tmp_path, "A", [record("own")]), source(tmp_path, "B", [])]
    expected_bytes = 2 * sum(len(Path(node["locator"]).read_bytes()) for node in nodes)
    result = run_query(snapshot(nodes, [("A", "B")]), tmp_path, strategy)
    assert result["status"] == "full"
    assert_coverage(result, {"A", "B"}, {"A", "B"})
    assert result["metrics"]["source_bytes_read"] == expected_bytes
    assert result["metrics"]["source_read_attempts"] == 4


def test_parse_failure_does_not_discard_bytes_already_read(tmp_path, strategy):
    nodes = [source(tmp_path, "A", []), source(tmp_path, "B", [record("own")])]
    broken = b'{"node_id":"A","facts":'
    Path(nodes[0]["locator"]).write_bytes(broken)
    successful_size = len(Path(nodes[1]["locator"]).read_bytes())
    result = run_query(snapshot(nodes, [("A", "B")]), tmp_path, strategy)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("B", "own")}
    assert_coverage(result, {"A", "B"}, {"B"}, failed={"A"})
    assert result["metrics"]["source_bytes_read"] == len(broken) + 2 * successful_size
    assert result["metrics"]["source_read_attempts"] == 3


def test_second_read_failure_preserves_first_read_byte_count(tmp_path, strategy, monkeypatch):
    node = source(tmp_path, "A", [record("own")])
    expected_bytes = len(Path(node["locator"]).read_bytes())
    original_read = coordinator._read_bytes
    attempts = []

    def fail_second_read(requested_path):
        attempts.append(str(requested_path))
        if len(attempts) == 2:
            raise OSError("injected second-read failure")
        return original_read(requested_path)

    monkeypatch.setattr(coordinator, "_read_bytes", fail_second_read)
    result = run_query(snapshot([node]), tmp_path, strategy)
    assert len(attempts) == 2
    assert result["status"] == "partial"
    assert result["facts"] == []
    assert_coverage(result, {"A"}, set(), failed={"A"})
    assert result["metrics"]["source_bytes_read"] == expected_bytes
    assert result["metrics"]["source_read_attempts"] == 2


@pytest.mark.parametrize("budget", [{"max_nodes": 1}, {"max_depth": 0}])
def test_budget_keeps_unread_descendants_in_expected_set(tmp_path, strategy, budget):
    nodes = [source(tmp_path, node, [record("own")]) for node in ["A", "B", "C"]]
    result = run_query(snapshot(nodes, [("A", "B"), ("B", "C")]), tmp_path, strategy, **budget)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("A", "own")}
    assert_coverage(result, {"A", "B", "C"}, {"A"}, skipped={"B", "C"})


def test_depth_budget_preserves_shared_node_reachable_by_shorter_path(tmp_path, strategy):
    nodes = [source(tmp_path, node, [record("own")]) for node in ["A", "B", "C", "D"]]
    state = snapshot(nodes, [("A", "B"), ("B", "C"), ("C", "D"), ("A", "D")])
    result = run_query(state, tmp_path, strategy, max_depth=1)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("A", "own"), ("B", "own"), ("D", "own")}
    assert_coverage(result, {"A", "B", "C", "D"}, {"A", "B", "D"}, skipped={"C"})


def test_explicit_view_reads_only_that_view(tmp_path, strategy):
    node = source(tmp_path, "A", [record("experiment", {"state": "draft"})], view_id="experiment")
    result = run_query(snapshot([node]), tmp_path, strategy, view="experiment")
    assert result["status"] == "full"
    assert set(facts_by_identity(result)) == {("A", "experiment")}
    assert result["facts"][0]["value"] == {"state": "draft"}
    assert_coverage(result, {"A"}, {"A"})


def test_repeated_identical_fact_is_deduplicated(tmp_path, strategy):
    same = record("shared")
    result = run_query(snapshot([source(tmp_path, "A", [same, copy.deepcopy(same)])]), tmp_path, strategy)
    assert result["status"] == "full"
    assert result["conflicts"] == []
    assert set(facts_by_identity(result)) == {("A", "shared")}


@pytest.mark.parametrize("conflict", ["value", "time", "revision"])
def test_conflicting_identity_is_removed_without_selecting_a_winner(tmp_path, strategy, conflict):
    original = record("conflicted", {"state": "old"})
    changed = copy.deepcopy(original)
    if conflict == "value":
        changed["value"] = {"state": "new"}
    elif conflict == "time":
        changed["occurred_at"] = "2026-10-08T12:00:00+08:00"
    else:
        changed["revision"] = 2
    facts = [record("safe"), original, changed, copy.deepcopy(original)]
    result = run_query(snapshot([source(tmp_path, "A", facts)]), tmp_path, strategy)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("A", "safe")}
    assert result["conflicts"]
    if conflict == "revision":
        assert "unresolved_version" in json.dumps(result["conflicts"])


def test_version_conflict_crossing_time_window_cannot_expose_old_fact(tmp_path, strategy):
    facts = [
        record("safe"),
        record("changed", {"state": "old"}, revision=1),
        record("changed", {"state": "new"}, revision=2, occurred_at="2026-10-13T12:00:00+08:00"),
    ]
    result = run_query(snapshot([source(tmp_path, "A", facts)]), tmp_path, strategy)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("A", "safe")}
    assert "unresolved_version" in json.dumps(result["conflicts"])


@pytest.mark.parametrize("left,right", [(True, 1), ({"flag": True}, {"flag": 1}), ([True], [1])])
def test_json_boolean_and_number_are_different_fact_values(tmp_path, strategy, left, right):
    facts = [record("safe"), record("typed", left), record("typed", right)]
    result = run_query(snapshot([source(tmp_path, "A", facts)]), tmp_path, strategy)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("A", "safe")}
    assert result["conflicts"]


def test_record_cannot_claim_a_different_authority_node(tmp_path, strategy):
    forged = record("forged", {"state": "untrusted"})
    forged["origin_node_id"] = "B"
    nodes = [source(tmp_path, "A", [forged]), source(tmp_path, "B", [record("authentic")])]
    result = run_query(snapshot(nodes, [("A", "B")]), tmp_path, strategy)
    assert result["status"] == "partial"
    assert set(facts_by_identity(result)) == {("B", "authentic")}
    assert_coverage(result, {"A", "B"}, {"B"}, failed={"A"})


def test_nonstandard_json_nan_rejects_the_source(tmp_path, strategy):
    node = source(tmp_path, "A", [record("invalid-number", {"score": float("nan")})])
    assert "NaN" in Path(node["locator"]).read_text(encoding="utf-8")
    result = run_query(snapshot([node]), tmp_path, strategy)
    assert result["status"] == "partial"
    assert result["facts"] == []
    assert_coverage(result, {"A"}, set(), failed={"A"})


def test_source_bytes_changing_within_one_query_are_rejected(tmp_path, strategy, monkeypatch):
    node = source(tmp_path, "A", [record("own", {"state": "before"})])
    path = Path(node["locator"])
    replacement = json.dumps({
        "node_id": "A", "view_id": "main",
        "facts": [record("own", {"state": "during-read"}, revision=2)],
    }).encode("utf-8")
    original_read = coordinator._read_bytes
    observed = []

    def read_then_change(requested_path):
        data = original_read(requested_path)
        if Path(requested_path) == path:
            observed.append(data)
            if len(observed) == 1:
                path.write_bytes(replacement)
        return data

    monkeypatch.setattr(coordinator, "_read_bytes", read_then_change)
    result = run_query(snapshot([node]), tmp_path, strategy)
    assert len(observed) >= 2
    assert observed[0] != observed[1] == replacement
    assert result["status"] == "partial"
    assert result["facts"] == []
    assert_coverage(result, {"A"}, set(), failed={"A"})
    assert result["metrics"]["source_bytes_read"] == sum(len(data) for data in observed)
    assert result["metrics"]["source_read_attempts"] == len(observed)


def test_query_reads_current_source_instead_of_reusing_previous_result(tmp_path, strategy):
    a = source(tmp_path, "A", [record("own", {"state": "old"})])
    state = snapshot([a])
    first = run_query(state, tmp_path, strategy)
    source(tmp_path, "A", [record("own", {"state": "new"}, revision=2)])
    second = run_query(state, tmp_path, strategy)
    assert first["facts"][0]["value"] == {"state": "old"}
    assert second["status"] == "full"
    assert set(facts_by_identity(second)) == {("A", "own")}
    assert second["facts"][0]["value"] == {"state": "new"}
    assert second["facts"][0]["revision"] == 2
    assert first["facts"][0]["sources"][0]["sha256"] != second["facts"][0]["sources"][0]["sha256"]


@pytest.mark.parametrize("mutation", ["missing-root", "duplicate-node", "dangling-edge", "cycle", "invalid-edge-kind"])
def test_invalid_registry_is_a_request_error(tmp_path, strategy, mutation):
    nodes = [source(tmp_path, node, []) for node in ["A", "B"]]
    state = snapshot(nodes, [("A", "B")])
    if mutation == "missing-root":
        state = snapshot([nodes[1]])
    elif mutation == "duplicate-node":
        state["nodes"].append(copy.deepcopy(nodes[0]))
    elif mutation == "dangling-edge":
        state["edges"].append({"source": "B", "target": "missing", "kind": "contains"})
    elif mutation == "cycle":
        state["edges"].append({"source": "B", "target": "A", "kind": "contains"})
    else:
        state["edges"][0]["kind"] = "unknown"
    with pytest.raises(QueryError):
        run_query(state, tmp_path, strategy)


@pytest.mark.parametrize("start,end", [(END, START), (START, START), ("2026-10-05T00:00:00", END), (START, "bad-time")])
def test_invalid_time_query_is_rejected(tmp_path, strategy, start, end):
    state = snapshot([source(tmp_path, "A", [])])
    with pytest.raises(QueryError):
        query(state, "A", tmp_path, start, end, strategy=strategy)


def page_bytes(page):
    return len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def test_pagination_preserves_every_fact_and_obeys_utf8_byte_budget():
    facts = [
        {"origin_node_id": "A", "record_id": str(i), "value": "\u4e2d\u6587\u8868\u60c5\U0001f600" * (i + 1)}
        for i in range(6)
    ]
    original = copy.deepcopy(facts)
    budget = max(page_bytes([fact]) for fact in facts)
    pages = paginate(facts, max_bytes=budget)
    assert len(pages) > 1
    assert all(pages)
    assert [fact for page in pages for fact in page] == facts
    assert all(page_bytes(page) <= budget for page in pages)
    assert facts == original


def test_single_fact_exact_page_boundary_and_one_byte_too_small():
    fact = {"origin_node_id": "A", "record_id": "one", "value": "\u4e2d"}
    required = page_bytes([fact])
    assert paginate([fact], max_bytes=required) == [[fact]]
    with pytest.raises(QueryError):
        paginate([fact], max_bytes=required - 1)


def test_pagination_empty_input_does_not_invent_a_fact():
    pages = paginate([], max_bytes=4096)
    assert [fact for page in pages for fact in page] == []
    assert all(page_bytes(page) <= 4096 for page in pages)
