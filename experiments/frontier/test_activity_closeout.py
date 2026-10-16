"""实验活动收口与小规模按需聚合验证。"""

import hashlib
import json

import pytest

from experiments.frontier import activity_closeout, mvp_light, node_workflow as workflow
from experiments.frontier.test_mvp_light import _copy_network


def _item(nodes, node_id):
    return next((nodes / node_id / workflow.ITEMS).glob("W-*"))


def _payload(nodes, node_id, identifier="a-closeout"):
    item = _item(nodes, node_id)
    validation = item / "validation-log.md"
    evidence = activity_closeout.evidence_ref(
        nodes / node_id,
        str(validation.relative_to(nodes / node_id)),
        line_start=1,
        line_end=1,
    )
    return {
        "id": identifier,
        "date": "2026-10-15",
        "summary": "完成本地收口验证",
        "status": "completed",
        "evidence_refs": [evidence],
    }


def _hashes(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def test_closeout_is_single_source_and_idempotent(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    leaf = nodes / "leaf"
    before = _hashes(leaf)
    payload = _payload(nodes, "leaf")

    created = activity_closeout.append_activity(leaf, _item(nodes, "leaf").name, payload)
    after_create = _hashes(leaf)
    unchanged = activity_closeout.append_activity(leaf, _item(nodes, "leaf").name, payload)
    after_repeat = _hashes(leaf)

    assert created["status"] == "created"
    assert unchanged["status"] == "unchanged"
    assert after_create == after_repeat
    changed = [path for path in before if before[path] != after_create[path]]
    assert changed == [str((_item(nodes, "leaf") / ".state.json").relative_to(leaf))]
    state = json.loads((_item(nodes, "leaf") / ".state.json").read_text(encoding="utf-8"))
    assert len(state["activity_records"]) == 1
    assert state["activity_records"][0]["evidence_refs"] == payload["evidence_refs"]


def test_closeout_conflict_and_bad_evidence_never_overwrite_state(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    leaf = nodes / "leaf"
    item_id = _item(nodes, "leaf").name
    payload = _payload(nodes, "leaf")
    activity_closeout.append_activity(leaf, item_id, payload)
    state_path = leaf / workflow.ITEMS / item_id / ".state.json"
    before = state_path.read_bytes()

    conflict = dict(payload, summary="被篡改的另一种事实")
    with pytest.raises(activity_closeout.CloseoutError, match="不同内容"):
        activity_closeout.append_activity(leaf, item_id, conflict)
    bad_ref = dict(payload, id="a-bad", evidence_refs=[dict(payload["evidence_refs"][0], sha256="0" * 64)])
    with pytest.raises(activity_closeout.CloseoutError, match="哈希已变化"):
        activity_closeout.append_activity(leaf, item_id, bad_ref)

    assert state_path.read_bytes() == before


def test_closeout_requires_evidence_and_does_not_depend_on_registry(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    leaf = nodes / "leaf"
    item_id = _item(nodes, "leaf").name
    (leaf / workflow.IDENTITY).unlink()
    payload = _payload(nodes, "leaf")
    with pytest.raises(activity_closeout.CloseoutError, match="evidence_refs"):
        activity_closeout.append_activity(leaf, item_id, dict(payload, evidence_refs=[]))
    result = activity_closeout.append_activity(leaf, item_id, payload)
    assert result["status"] == "created"


def test_two_children_are_queried_on_demand_and_parent_keeps_gaps(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    middle_item = _item(nodes, "middle")
    leaf_item = _item(nodes, "leaf")
    activity_closeout.append_activity(nodes / "middle", middle_item.name, _payload(nodes, "middle", "a-middle"))
    activity_closeout.append_activity(nodes / "leaf", leaf_item.name, _payload(nodes, "leaf", "a-leaf"))
    before_root = _hashes(nodes / "root")

    result = workflow.aggregate(nodes / "root", nodes)
    window = mvp_light.activity_window(result, "2026-10-13", "2026-10-19")

    assert result["status"] == "full"
    assert window["records"] == sorted(window["records"], key=lambda record: (
        record["date"], record["node_id"], record["work_item_id"], record["activity_id"]))
    assert {(record["node_id"], record["activity_id"]) for record in window["records"]} == {
        ("leaf", "a-leaf"), ("middle", "a-middle")}
    assert "root" in window["unknown_date_nodes"]
    assert _hashes(nodes / "root") == before_root


def test_denied_child_is_partial_and_not_silently_empty(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    middle_item = _item(nodes, "middle")
    leaf_item = _item(nodes, "leaf")
    activity_closeout.append_activity(nodes / "middle", middle_item.name, _payload(nodes, "middle", "a-middle"))
    activity_closeout.append_activity(nodes / "leaf", leaf_item.name, _payload(nodes, "leaf", "a-leaf"))

    result = workflow.aggregate(nodes / "root", nodes, denied={"leaf"})
    window = mvp_light.activity_window(result, "2026-10-13", "2026-10-19")

    assert result["status"] == "partial"
    assert result["coverage"]["failed"] == {"leaf": "本次请求明确拒绝读取"}
    assert [(record["node_id"], record["activity_id"]) for record in window["records"]] == [("middle", "a-middle")]
    assert "leaf" not in window["unknown_date_nodes"]
    assert "root" in window["unknown_date_nodes"]


def test_changed_evidence_source_turns_activity_into_an_explicit_gap(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    leaf = nodes / "leaf"
    item_path = _item(nodes, "leaf")
    activity_closeout.append_activity(leaf, item_path.name, _payload(nodes, "leaf", "a-leaf"))
    validation = item_path / "validation-log.md"
    validation.write_text(validation.read_text(encoding="utf-8") + "\n证据后来发生变化。\n", encoding="utf-8")

    result = workflow.aggregate(nodes / "root", nodes)

    assert result["status"] == "partial"
    assert "leaf" in result["coverage"]["failed"]
    assert all(record["node_id"] != "leaf" for record in mvp_light.extract_activity_records(result))


def test_node_budget_marks_unqueried_child_as_skipped(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    result = workflow.aggregate(nodes / "root", nodes, max_nodes=2)

    assert result["status"] == "partial"
    assert result["coverage"]["visited"] == ["middle", "root"]
    assert result["coverage"]["skipped"] == {"leaf": "node_budget"}
    assert "leaf" not in [fact["origin_node_id"] for fact in result["facts"]]


def test_line_evidence_survives_append_but_rejects_changed_referenced_line(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    leaf = nodes / "leaf"
    item = _item(nodes, "leaf")
    validation = item / "validation-log.md"
    validation.write_text("第一条验证通过\n第二条待执行\n", encoding="utf-8")
    ref = activity_closeout.evidence_ref(leaf, str(validation.relative_to(leaf)), 1, 1, hash_scope="lines")
    payload = dict(_payload(nodes, "leaf"), evidence_refs=[ref])
    activity_closeout.append_activity(leaf, item.name, payload)

    validation.write_text(validation.read_text(encoding="utf-8") + "第三条验证完成\n", encoding="utf-8")
    result = workflow.aggregate(nodes / "root", nodes)
    assert result["status"] == "full"
    records = mvp_light.extract_activity_records(result)
    assert len(records) == 1
    assert activity_closeout.append_activity(leaf, item.name, payload)["status"] == "unchanged"

    validation.write_text("第一条实际未执行\n第二条待执行\n第三条验证完成\n", encoding="utf-8")
    with pytest.raises(activity_closeout.CloseoutError, match="哈希已变化"):
        activity_closeout.append_activity(leaf, item.name, payload)
    result = workflow.aggregate(nodes / "root", nodes)
    assert result["status"] == "partial"
    assert "leaf" in result["coverage"]["failed"]
    assert not mvp_light.extract_activity_records(result)


@pytest.mark.parametrize("replacement", ["前面插入一行\n原证据\n", ""])
def test_line_evidence_moving_or_removal_is_not_silently_accepted(tmp_path, replacement):
    nodes, _ = _copy_network(tmp_path)
    leaf, item = nodes / "leaf", _item(nodes, "leaf")
    validation = item / "validation-log.md"
    validation.write_text("原证据\n", encoding="utf-8")
    ref = activity_closeout.evidence_ref(leaf, str(validation.relative_to(leaf)), 1, 1, hash_scope="lines")
    activity_closeout.append_activity(leaf, item.name, dict(_payload(nodes, "leaf"), evidence_refs=[ref]))
    validation.write_text(replacement, encoding="utf-8")
    result = workflow.aggregate(nodes / "root", nodes)
    assert result["status"] == "partial"
    assert "leaf" in result["coverage"]["failed"]


@pytest.mark.parametrize("scope", ["paragraph", None, 1])
def test_unknown_hash_scope_never_writes_activity(tmp_path, scope):
    nodes, _ = _copy_network(tmp_path)
    leaf, item = nodes / "leaf", _item(nodes, "leaf")
    payload = _payload(nodes, "leaf")
    payload["evidence_refs"][0]["hash_scope"] = scope
    before = (item / ".state.json").read_bytes()
    with pytest.raises(activity_closeout.CloseoutError):
        activity_closeout.append_activity(leaf, item.name, payload)
    assert (item / ".state.json").read_bytes() == before


def test_closeout_rejects_symlinked_workflow_and_out_of_inventory_evidence(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    leaf, item = nodes / "leaf", _item(nodes, "leaf")
    other = tmp_path / "other"
    other.mkdir()
    (other / ".agent-workflow").symlink_to(leaf / ".agent-workflow", target_is_directory=True)
    before = (item / ".state.json").read_bytes()
    with pytest.raises(activity_closeout.CloseoutError, match="符号链接"):
        activity_closeout.append_activity(other, item.name, _payload(nodes, "leaf"))
    outside = leaf / "outside.md"
    outside.write_text("非工作流证据\n", encoding="utf-8")
    with pytest.raises(activity_closeout.CloseoutError, match="Markdown 或 JSON"):
        activity_closeout.evidence_ref(leaf, "outside.md")
    assert (item / ".state.json").read_bytes() == before


def test_closeout_rejects_self_referencing_state_evidence(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    leaf, item = nodes / "leaf", _item(nodes, "leaf")
    state_path = item / ".state.json"
    before = state_path.read_bytes()
    ref = {"path": str(state_path.relative_to(leaf)), "sha256": hashlib.sha256(before).hexdigest(),
           "line_start": 1, "line_end": 1}
    with pytest.raises(activity_closeout.CloseoutError, match="不能引用 .state.json"):
        activity_closeout.append_activity(leaf, item.name, dict(_payload(nodes, "leaf"), evidence_refs=[ref]))
    assert state_path.read_bytes() == before
