"""固定事实包盲测和 Agent 声明契约验证。"""

import hashlib
import json
from pathlib import Path

import pytest

from experiments.frontier import agent_blind_eval, mvp_light


def _summary():
    return {
        "facts": [
            {"node_id": "alpha", "work_item_id": "W-alpha", "title": "完成自治验证",
             "status": "completed", "completed_at": "2026-10-15T09:00:00+08:00",
             "completed_at_status": "known", "documents": [{"content": "不应暴露"}],
             "source_hashes": ["secret"]},
            {"node_id": "beta", "work_item_id": "W-beta", "title": "聚合验证进行中",
             "status": "in_progress", "completed_at": None, "completed_at_status": "unknown",
             "documents": [{"content": "不应暴露"}], "source_hashes": ["secret"]},
        ]
    }


def _valid_draft(summary):
    sections = []
    for fact in summary["facts"]:
        ref = mvp_light.fact_key(fact)
        sections.append({
            "fact_refs": [ref],
            "claims": [{"fact_ref": ref, "field": field, "value": fact[field]}
                       for field in ("title", "status", "completed_at", "completed_at_status")],
            "text": fact["title"],
        })
    return {"sections": sections, "omitted": []}


def test_fact_package_is_bounded_and_excludes_source_documents():
    package = agent_blind_eval.fact_package(_summary())
    encoded = json.dumps(package, ensure_ascii=False)

    assert [fact["fact_ref"] for fact in package["facts"]] == ["alpha/W-alpha", "beta/W-beta"]
    assert "不应暴露" not in encoded
    assert "source_hashes" not in encoded
    assert package["schema_version"] == 2
    assert package["output_template"]["sections"][0]["claims"][0]["fact_ref"] == "alpha/W-alpha"


def test_valid_draft_is_accepted_and_omission_is_explicit():
    summary = _summary()
    result = agent_blind_eval.evaluate(summary, _valid_draft(summary))

    assert result == {
        "accepted": True,
        "covered": ["alpha/W-alpha", "beta/W-beta"],
        "omitted": [],
        "text_semantics_verified": False,
    }

    omitted = _valid_draft(summary)
    omitted["sections"] = omitted["sections"][:1]
    omitted["omitted"] = ["beta/W-beta"]
    assert agent_blind_eval.evaluate(summary, omitted)["accepted"] is True


@pytest.mark.parametrize("mutation", ["missing_claim_ref", "wrong_value", "unknown_ref", "duplicate_ref"])
def test_contract_rejects_structured_agent_errors(mutation):
    summary = _summary()
    draft = _valid_draft(summary)
    if mutation == "missing_claim_ref":
        draft["sections"][0]["claims"][0].pop("fact_ref")
    elif mutation == "wrong_value":
        draft["sections"][0]["claims"][0]["value"] = "虚构状态"
    elif mutation == "unknown_ref":
        draft["sections"][0]["fact_refs"] = ["unknown/W-nope"]
        draft["sections"][0]["claims"][0]["fact_ref"] = "unknown/W-nope"
    else:
        draft["sections"][0]["fact_refs"].append("beta/W-beta")

    result = agent_blind_eval.evaluate(summary, draft)

    assert result["accepted"] is False
    assert result["text_semantics_verified"] is False


def test_free_text_hallucination_remains_explicitly_unverified():
    summary = _summary()
    draft = _valid_draft(summary)
    draft["sections"][1]["text"] = "beta 已完成并上线。"

    result = agent_blind_eval.evaluate(summary, draft)

    assert result["accepted"] is True
    assert result["text_semantics_verified"] is False


def test_verified_renderer_ignores_contradictory_free_text():
    summary = _summary()
    draft = _valid_draft(summary)
    draft["sections"][1]["text"] = "beta 已完成并上线。"

    rendered = agent_blind_eval.render_verified(summary, draft)

    assert "beta 已完成并上线" not in rendered
    assert r"聚合验证进行中：状态=in\_progress；完成时间=未记录" in rendered
    assert r"事实引用：beta/W\-beta" in rendered


@pytest.mark.parametrize("omitted", [
    ["unknown/W-nope"], ["ghost/W-nope\n- beta 已完成并上线。"],
    ["beta/W-beta", "beta/W-beta"],
])
def test_omitted_must_be_known_unique_references(omitted):
    summary = _summary()
    draft = _valid_draft(summary)
    draft["sections"] = draft["sections"][:1]
    draft["omitted"] = omitted
    result = agent_blind_eval.render_with_fallback(summary, draft)
    assert result["mode"] == "deterministic_fallback"
    assert "ghost" not in result["report"]
    assert "已完成并上线" not in result["report"]
    assert r"状态=in\_progress" in result["report"]


def test_empty_partial_result_preserves_source_gaps():
    summary = {"facts": [], "status": "partial", "coverage": {
        "expected": ["root", "leaf"], "succeeded": [],
        "failed": {"root": "读取失败"}, "skipped": {"leaf": "节点预算"},
    }}
    report = agent_blind_eval.render_verified(summary, {"sections": [], "omitted": []})
    assert "来源聚合状态：partial" in report
    assert "读取失败 root：读取失败" in report
    assert "跳过 leaf：节点预算" in report
    assert "不能据此判断没有工作" in report


@pytest.mark.parametrize("raw", [
    '{"sections": [], "sections": [], "omitted": []}',
    '{"sections": [], "omitted": NaN}',
    '```json\n{}\n```',
    '{"sections":',
    '[' * 1200 + ']' * 1200,
    ' ' * (agent_blind_eval.MAX_DRAFT_BYTES + 1),
])
def test_invalid_raw_output_is_rejected_without_silent_repairs(raw):
    summary = _summary()
    result = agent_blind_eval.render_with_fallback(summary, raw)
    assert result["evaluation"]["accepted"] is False
    assert result["mode"] == "deterministic_fallback"
    assert "事实展示：2；明确省略：0" in result["report"]


def test_accepted_raw_draft_keeps_explicit_omission_and_cannot_write_sources():
    summary = _summary()
    draft = _valid_draft(summary)
    draft["sections"] = draft["sections"][:1]
    draft["omitted"] = ["beta/W-beta"]
    original = json.dumps(summary, ensure_ascii=False)
    result = agent_blind_eval.render_with_fallback(summary, json.dumps(draft))
    assert result["mode"] == "agent_ordered"
    assert "已明确省略" in result["report"]
    assert json.dumps(summary, ensure_ascii=False) == original


def test_templates_only_reference_actual_facts_and_budget_rejects_oversize():
    summary = _summary()
    summary["facts"] = [summary["facts"][1]]
    raw = agent_blind_eval.dumps_package(summary)
    assert "alpha/W-alpha" not in raw
    assert "completed\"" not in raw
    summary["facts"][0]["title"] = "测" * 6000
    with pytest.raises(ValueError, match="预算"):
        agent_blind_eval.dumps_package(summary)


def test_duplicate_fact_identity_cannot_diverge_between_check_and_render():
    summary = _summary()
    draft = _valid_draft(summary)
    summary["facts"].append(dict(summary["facts"][1], status="completed"))
    with pytest.raises(ValueError, match="重复引用"):
        agent_blind_eval.render_verified(summary, draft)


def test_duplicate_claim_field_is_rejected():
    summary = _summary()
    draft = _valid_draft(summary)
    draft["sections"][0]["claims"].append(draft["sections"][0]["claims"][0])
    assert agent_blind_eval.evaluate(summary, draft)["accepted"] is False


def test_native_final_evidence_replays_without_repairs():
    base = Path(__file__).parent / "evidence"
    audit = json.loads((base / "mvp-light-agent-blind-20261015-audited.json").read_text())
    outcomes = {}
    for run in audit["runs"]:
        raw = run["raw_final"]
        assert hashlib.sha256(raw.encode()).hexdigest() == run["raw_final_sha256"]
        checked = agent_blind_eval.evaluate(audit["summary_input_for_replay"], raw)
        assert checked == run["evaluation"]
        outcomes[run["agent_id"]] = checked["accepted"]
    assert outcomes == {"blind_agent_" + key: key in "cd" for key in "abcdef"}

    frozen = base / "mvp-light-agent-frozen-20261015"
    manifest = json.loads((frozen / "manifest.json").read_text())
    assert hashlib.sha256((frozen / "input.txt").read_bytes()).hexdigest() == manifest["input_sha256"]
    summary = json.loads((frozen / "summary.json").read_text())
    for run in json.loads((frozen / "results.json").read_text())["runs"]:
        assert agent_blind_eval.evaluate(summary, run["raw_final"]) == run["evaluation"]
        assert agent_blind_eval.render_verified(summary, run["raw_final"]) == run["rendered"]


def test_local_closeout_and_partial_aggregate_survive_invalid_agent_output(tmp_path):
    from experiments.frontier import activity_closeout, node_workflow as workflow
    from experiments.frontier.test_mvp_light import _copy_network, _file_hashes

    nodes, _ = _copy_network(tmp_path)
    middle = nodes / "middle"
    item = next((middle / workflow.ITEMS).glob("W-*"))
    parent_before = _file_hashes(nodes / "root")
    payload = {"id": "roundtrip-1", "date": "2026-10-15", "summary": "完成本地记录验证",
               "status": "completed", "evidence_refs": [activity_closeout.evidence_ref(
                   middle, str((item / "validation-log.md").relative_to(middle)), 1, 1)]}
    assert activity_closeout.append_activity(middle, item.name, payload)["status"] == "created"
    assert activity_closeout.append_activity(middle, item.name, payload)["status"] == "unchanged"
    assert _file_hashes(nodes / "root") == parent_before
    before_read = _file_hashes(nodes)
    aggregated = workflow.aggregate(nodes / "root", nodes, denied={"leaf"})
    summary = mvp_light.summarize(aggregated)
    report = agent_blind_eval.render_with_fallback(summary, "not JSON")
    assert report["mode"] == "deterministic_fallback"
    assert "来源聚合状态：partial" in report["report"]
    assert "读取失败 leaf" in report["report"]
    assert len(mvp_light.activity_window(aggregated, "2026-10-13", "2026-10-19")["records"]) == 1
    assert _file_hashes(nodes) == before_read
