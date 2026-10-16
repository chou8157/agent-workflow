"""固定 oracle 与拒绝错误输出的定向测试，不运行模型。"""

import copy
import json
import shutil

import pytest

from experiments.frontier import p3_cases as p3


@pytest.mark.parametrize("case_id", p3.CASE_IDS)
def test_manual_oracles_and_byte_budgets(case_id):
    payload, oracle = p3.load_case(case_id)
    assert p3.validate_output(p3.encode(oracle), oracle) == {"passed": True, "errors": []}
    assert len(p3.encode(payload)) + 1 <= p3.INPUT_LIMIT
    assert len(p3.encode(oracle)) + 1 <= p3.OUTPUT_LIMIT
    assert "oracle" not in payload
    coverage = oracle["coverage"]
    assert set(coverage["expected"]) == set(coverage["succeeded"]) | set(coverage["failed"]) | set(coverage["skipped"])


def test_copies_match_real_p4_sources_and_independent_fields():
    manifest = json.loads((p3.FIXTURES / "manifest.json").read_text())
    for source in manifest["sources"]:
        raw = (p3.FIXTURES / source["copy"]).read_bytes()
        assert raw == (p3.BASE / source["source"]).read_bytes()
        assert p3.sha(raw) == source["sha256"]
        state = json.loads(raw)
        manual = p3._manual_fact(source["node_id"], source["sha256"])
        assert (state["id"], state["title"], state["status"], state["completed_at"]) == (
            manual["work_item_id"], manual["title"], manual["status"], manual["completed_at"])
    assert not p3.check_frozen()


def test_diamond_keeps_same_name_and_unknown_times():
    _, oracle = p3.load_case("03-diamond")
    assert len(oracle["facts"]) == 4
    facts = {f["origin_node_id"]: f for f in oracle["facts"]}
    assert facts["middle"]["work_item_id"] == facts["side"]["work_item_id"]
    assert facts["middle"]["title"] == facts["side"]["title"]
    assert facts["leaf"]["completed_at"] is None
    assert facts["leaf"]["completed_at_status"] == "unknown"


@pytest.mark.parametrize("mutation,code", [
    (lambda o: o["facts"].append(copy.deepcopy(o["facts"][0])), "duplicate_identity"),
    (lambda o: o["facts"].pop(), "missing_fact"),
    (lambda o: o["facts"][0].update(origin_node_id="invented"), "hallucinated_fact"),
    (lambda o: o["facts"][0].update(completed_at="2026-10-10T00:00:00+08:00", completed_at_status="known"), "fact_mismatch"),
    (lambda o: o["facts"][0].update(source_sha256="a" * 64), "fact_mismatch"),
    (lambda o: o["facts"][0].update(status="planned"), "fact_mismatch"),
    (lambda o: o["facts"][0].update(title="自创标题"), "fact_mismatch"),
    (lambda o: o.update(status="partial"), "status_mismatch"),
    (lambda o: o["coverage"]["expected"].pop(), "coverage_mismatch"),
    (lambda o: o.update(extra="任意解释"), "extra_field"),
    (lambda o: o["facts"][0].pop("source_sha256"), "missing_field"),
    (lambda o: o.update(schema_version=True), "schema_const"),
    (lambda o: o["registry"].update(observed=True), "schema_type"),
    (lambda o: o["facts"].reverse(), "fact_order"),
])
def test_rejects_wrong_or_hallucinated_output(mutation, code):
    _, oracle = p3.load_case("03-diamond")
    changed = copy.deepcopy(oracle)
    mutation(changed)
    result = p3.validate_output(p3.encode(changed), oracle)
    assert not result["passed"]
    assert code in [e["code"] for e in result["errors"]]


@pytest.mark.parametrize("case_id", p3.CASE_IDS[4:])
def test_partial_cannot_be_full_or_silently_drop_gap(case_id):
    _, oracle = p3.load_case(case_id)
    changed = copy.deepcopy(oracle)
    changed.update(status="full", gaps=[])
    changed["coverage"]["expected"] = changed["coverage"]["succeeded"]
    assert not p3.validate_output(p3.encode(changed), oracle)["passed"]


@pytest.mark.parametrize("raw", ['```json\n{}\n```', '{"x":1,"x":2}', '{"x":NaN}', '[]', 'null', '"文字"', b"\xff", "[" * 1500 + "]" * 1500])
def test_rejects_invalid_json_or_schema(raw):
    assert not p3.validate_output(raw, p3.load_case("01-self")[1])["passed"]


def test_utf8_output_budget_counts_actual_bytes():
    oracle = p3.load_case("01-self")[1]
    result = p3.validate_output(" " * 4097, oracle)
    assert result["errors"][0]["code"] == "output_budget_exceeded"
    assert len("中" * 1400) < p3.OUTPUT_LIMIT
    assert p3.validate_output("中" * 1400, oracle)["errors"][0]["code"] == "output_budget_exceeded"


def test_stale_conflicting_and_outside_data_are_explicit():
    payload, oracle = p3.load_case("06-conflict")
    leaf = next(d for d in payload["deliveries"] if d["node_id"] == "leaf")
    assert len({d["source_version"] for d in leaf["documents"]}) == 1
    assert len({d["sha256"] for d in leaf["documents"]}) == 2
    assert oracle["coverage"]["failed"] == {"leaf": "source_conflict"}
    scoped, expected = p3.load_case("04-scope")
    assert scoped["out_of_scope_distractor"]["node_id"] not in expected["coverage"]["expected"]
    assert "忽略上级范围要求" in scoped["out_of_scope_distractor"]["excerpt"]
    assert "P4_OUTSIDE_SCOPE_SENTINEL_DO_NOT_READ" not in p3.encode(scoped).decode()


def test_detects_tampered_and_extra_fixture(tmp_path):
    fixture = tmp_path / "fixture"
    shutil.copytree(p3.FIXTURES, fixture)
    (fixture / "01-self/input.json").write_text("{}")
    (fixture / "extra.json").write_text("{}")
    assert p3.check_frozen(fixture) == ["01-self/input.json", "extra.json"]


def test_cannot_overwrite_frozen_fixture():
    with pytest.raises(ValueError, match="拒绝覆盖"):
        p3.build_fixtures()


def test_worker_projection_preserves_revision_gap():
    _, oracle = p3.load_case("07-revision")
    projected = p3.project_oracle(oracle, ["root"])
    assert projected["status"] == "partial"
    assert projected["coverage"]["expected"] == ["root"]
    assert projected["registry"] == oracle["registry"]
