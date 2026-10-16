"""轻量 MVP 验证：SQLite 关系 + 确定性聚合 + 简单报告。"""

import hashlib
import json
import shutil
from pathlib import Path

from experiments.frontier import mvp_light, node_workflow as workflow


FIXTURES = Path(__file__).resolve().parent / "fixtures/p4"


def _copy_network(tmp_path):
    nodes = tmp_path / "nodes"
    shutil.copytree(FIXTURES / "nodes", nodes)
    registry = tmp_path / "control/registry.sqlite"
    workflow.network_initialize(registry, "sqlite")
    parents = {"root": None, "middle": "root", "leaf": "middle"}
    for node_id, parent in parents.items():
        project = nodes / node_id
        workflow.enable(project, registry, "sqlite")
        workflow.join(project, parent)
    return nodes, registry


def _file_hashes(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def test_light_mvp_generates_stable_three_node_report_without_writing_sources(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    before = _file_hashes(nodes)

    first = workflow.aggregate(nodes / "root", nodes)
    second = workflow.aggregate(nodes / "root", nodes)
    first_data = mvp_light.summarize(first)
    second_data = mvp_light.summarize(second)

    assert first["status"] == "full"
    assert first_data["coverage"] == {
        "expected": ["leaf", "middle", "root"],
        "visited": ["leaf", "middle", "root"],
        "succeeded": ["leaf", "middle", "root"],
        "failed": {},
        "skipped": {},
    }
    assert [fact["node_id"] for fact in first_data["facts"]] == ["leaf", "middle", "root"]
    assert first_data["facts"] == second_data["facts"]
    report = mvp_light.render_markdown(first)
    assert all("[{}]".format(node_id) in report for node_id in ("root", "middle", "leaf"))
    assert "未记录日期" in report
    assert _file_hashes(nodes) == before


def test_light_mvp_marks_denied_node_as_gap_instead_of_silent_empty(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    result = workflow.aggregate(nodes / "root", nodes, denied={"leaf"})
    data = mvp_light.summarize(result)

    assert data["status"] == "partial"
    assert data["coverage"]["expected"] == ["leaf", "middle", "root"]
    assert data["coverage"]["failed"] == {"leaf": "本次请求明确拒绝读取"}
    assert [fact["node_id"] for fact in data["facts"]] == ["middle", "root"]
    assert "[leaf] 本次请求明确拒绝读取" in mvp_light.render_markdown(result)


def test_activity_window_ignores_unstructured_log_dates_and_requires_activity_records(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    for node_id, body in (
        ("middle", "\n## 2026-10-13 - 本周升级\n\n完成升级验证。\n"),
        ("leaf", "\n日期：2026-10-14\n\n完成任务拆分。\n"),
    ):
        item = next((nodes / node_id / workflow.ITEMS).glob("W-*"))
        validation = item / "validation-log.md"
        validation.write_text(validation.read_text(encoding="utf-8") + body, encoding="utf-8")

    result = workflow.aggregate(nodes / "root", nodes)
    window = mvp_light.activity_window(result, "2026-10-13", "2026-10-19")

    assert window["records"] == []
    assert window["unknown_date_nodes"] == ["leaf", "middle", "root"]
    assert window["recorded_outside_window_nodes"] == []
    report = mvp_light.render_activity_window(result, "2026-10-13", "2026-10-19")
    assert "不能判断该范围内是否有工作" in report


def test_activity_window_reads_structured_state_records_and_preserves_sources(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    for node_id, records in (
        ("middle", [{"id": "a-1", "date": "2026-10-13", "summary": "完成升级验证", "status": "completed"}]),
        ("leaf", [{"id": "a-1", "date": "2026-10-14", "summary": "完成任务拆分", "status": "in_progress"}]),
    ):
        item = next((nodes / node_id / workflow.ITEMS).glob("W-*"))
        state_path = item / ".state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["activity_records"] = records
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = workflow.aggregate(nodes / "root", nodes)
    window = mvp_light.activity_window(result, "2026-10-13", "2026-10-19")

    assert [(record["node_id"], record["date"], record["summary"]) for record in window["records"]] == [
        ("middle", "2026-10-13", "完成升级验证"), ("leaf", "2026-10-14", "完成任务拆分")]
    assert window["unknown_date_nodes"] == ["root"]
    assert all(record["line_start"] == 1 for record in window["records"])


def test_activity_window_reports_unknown_work_item_when_node_has_partial_activity_coverage(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    source = next((nodes / "root" / workflow.ITEMS).glob("W-*"))
    extra = source.with_name("W-extra")
    shutil.copytree(source, extra)
    state_path = extra / ".state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["id"] = "W-extra"
    state["title"] = "没有活动记录的工作项"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    original = source / ".state.json"
    state = json.loads(original.read_text(encoding="utf-8"))
    state["activity_records"] = [{
        "id": "a-root", "date": "2026-10-14", "summary": "完成根节点收口", "status": "completed",
    }]
    original.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = workflow.aggregate(nodes / "root", nodes)
    window = mvp_light.activity_window(result, "2026-10-13", "2026-10-19")

    assert window["unknown_date_nodes"] == ["leaf", "middle"]
    assert "root/W-extra" in window["unknown_date_work_items"]
    assert "工作项 W-extra 没有可识别的日期记录" in mvp_light.render_activity_window(
        result, "2026-10-13", "2026-10-19")


def test_invalid_activity_record_is_reported_as_node_gap(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    item = next((nodes / "leaf" / workflow.ITEMS).glob("W-*"))
    state_path = item / ".state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["activity_records"] = [{
        "id": "bad-date", "date": "not-a-date", "summary": "不应进入汇总", "status": "completed",
    }]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = workflow.aggregate(nodes / "root", nodes)

    assert result["status"] == "partial"
    assert "leaf" in result["coverage"]["failed"]
    assert any("activity_records" in gap["reason"] for gap in result["gaps"]["leaf"])
    assert all(record["node_id"] != "leaf" for record in mvp_light.extract_activity_records(result))


def test_agent_draft_must_reference_known_facts_and_account_for_omissions(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    summary = mvp_light.summarize(workflow.aggregate(nodes / "root", nodes))
    keys = [mvp_light.fact_key(fact) for fact in summary["facts"]]
    draft = {
        "sections": [{
            "fact_refs": keys[:2],
            "claims": [
                {"fact_ref": key, "field": "status", "value": "completed"}
                for key in keys[:2]
            ],
            "text": "已完成两项工作。",
        }],
        "omitted": keys[2:],
    }

    checked = mvp_light.validate_agent_draft(summary, draft)
    assert checked["covered"] == sorted(keys[:2])
    assert checked["omitted"] == sorted(keys[2:])

    bad = {"sections": [{
        "fact_refs": ["unknown/W-missing"],
        "claims": [{"fact_ref": "unknown/W-missing", "field": "status", "value": "completed"}],
        "text": "不存在的事实。",
    }], "omitted": keys}
    try:
        mvp_light.validate_agent_draft(summary, bad)
    except ValueError as error:
        assert "未知事实" in str(error)
    else:
        raise AssertionError("未知事实未被拒绝")


def test_agent_claim_contract_rejects_status_mismatch(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    summary = mvp_light.summarize(workflow.aggregate(nodes / "root", nodes))
    target = summary["facts"][0]
    key = mvp_light.fact_key(target)
    draft = {
        "sections": [{
            "fact_refs": [key],
            "claims": [{"fact_ref": key, "field": "status", "value": "in_progress"}],
            "text": "状态已完成。",
        }],
        "omitted": [mvp_light.fact_key(fact) for fact in summary["facts"][1:]],
    }

    try:
        mvp_light.validate_agent_draft(summary, draft)
    except ValueError as error:
        assert "不一致" in str(error)
    else:
        raise AssertionError("状态不一致的 Agent 声明未被拒绝")


def test_agent_draft_rejects_undefined_fields():
    summary = {"facts": [{
        "node_id": "root", "work_item_id": "W-one", "title": "一项工作",
        "status": "completed", "completed_at": None, "completed_at_status": "unknown",
    }]}
    ref = "root/W-one"
    base = {
        "sections": [{
            "fact_refs": [ref],
            "claims": [{"fact_ref": ref, "field": "status", "value": "completed"}],
            "text": "一项工作已完成",
        }],
        "omitted": [],
    }
    for location in ("root", "section", "claim"):
        draft = json.loads(json.dumps(base, ensure_ascii=False))
        if location == "root":
            draft["extra"] = True
        elif location == "section":
            draft["sections"][0]["extra"] = True
        else:
            draft["sections"][0]["claims"][0]["extra"] = True
        try:
            mvp_light.validate_agent_draft(summary, draft)
        except ValueError as error:
            assert "未定义字段" in str(error)
        else:
            raise AssertionError("未定义字段未被拒绝: {}".format(location))
