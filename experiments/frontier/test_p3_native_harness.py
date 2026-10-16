"""原生调用审计器的合成日志回归；不代表真实模型评测。"""

import copy
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

from experiments.frontier import p3_cases as cases
from experiments.frontier import p3_native_harness as harness


@pytest.fixture
def plan(tmp_path):
    return harness.create_plan(tmp_path / "run", "p3test")


def _call(plan, case_id="01-self", strategy="C", task_id="final"):
    return next(c for c in plan["calls"] if c["case_id"] == case_id and c["strategy"] == strategy
                and c["repeat"] == 1 and c["task_id"] == task_id)


def _records(plan, call):
    harness.prepare_call(plan, call["call_id"])
    raw = Path(call["input_path"]).read_text()
    _, oracle = cases.load_case(call["case_id"])
    final = cases.encode(cases.project_oracle(oracle, call["nodes"])).decode()
    return [
        {"type": "session_meta", "payload": {"id": "synthetic-session", "timestamp": plan["created_at"],
            "model_provider": "synthetic-test", "source": {"subagent": {"thread_spawn": {"agent_path": call["agent_path"]}}}}},
        {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "xhigh"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "read1",
            "input": harness.read_tool_code(call["input_path"])}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "read1", "output": [
            {"type": "input_text", "text": "Script completed"},
            {"type": "input_text", "text": json.dumps({"exit_code": 0, "output": raw})}]}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 30, "output_tokens": 10,
                                  "reasoning_output_tokens": 5, "total_tokens": 110},
            "last_token_usage": {"input_tokens": 60, "output_tokens": 10}}}},
        {"type": "response_item", "timestamp": (datetime.fromisoformat(plan["created_at"]) + timedelta(seconds=2)).isoformat(),
         "payload": {"type": "message", "role": "assistant", "phase": "final_answer",
            "content": [{"type": "output_text", "text": final}]}},
        {"type": "event_msg", "payload": {"type": "task_complete"}},
    ]


def _save_rollout(tmp_path, records, name="rollout.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


def test_plan_contains_real_dependent_calls(plan):
    assert len(plan["calls"]) == 138
    assert sum(c["is_final"] for c in plan["calls"]) == 72
    assert len({c["agent_path"] for c in plan["calls"]}) == 138
    assert {s: sum(c["strategy"] == s for c in plan["calls"]) for s in harness.STRATEGIES} == {"C": 24, "H": 66, "M": 48}
    h = [c for c in plan["calls"] if c["case_id"] == "02-multilevel" and c["strategy"] == "H" and c["repeat"] == 1]
    assert [c["task_id"] for c in h] == ["leaf", "middle", "final"]
    assert h[1]["dependencies"] == [h[0]["call_id"]]
    assert h[2]["dependencies"] == [h[1]["call_id"]]
    m = [c for c in plan["calls"] if c["case_id"] == "02-multilevel" and c["strategy"] == "M" and c["repeat"] == 1]
    assert [c["task_id"] for c in m] == ["batch1", "final"]
    assert m[0]["local_nodes"] == ["leaf", "middle"]


def test_prepare_has_no_oracle_or_other_read_permission(plan):
    call = _call(plan)
    spawn = harness.prepare_call(plan, call["call_id"])
    assert spawn["fork_turns"] == "none"
    assert "model" not in spawn and "reasoning_effort" not in spawn
    payload = json.loads(Path(call["input_path"]).read_text())
    assert "oracle" not in payload
    assert harness.read_tool_code(call["input_path"]) in spawn["message"]
    assert Path(call["input_path"]).stat().st_size < cases.INPUT_LIMIT


def test_parent_requires_real_child_output_and_keeps_it_exact(plan):
    parent = _call(plan, "02-multilevel", "H", "middle")
    child = _call(plan, "02-multilevel", "H", "leaf")
    with pytest.raises(FileNotFoundError):
        harness.prepare_call(plan, parent["call_id"])
    harness.prepare_call(plan, child["call_id"])
    oracle = cases.project_oracle(cases.load_case("02-multilevel")[1], child["nodes"])
    oracle["facts"][0]["title"] = "故意错误的下级输出"
    Path(child["output_path"]).write_bytes(cases.encode(oracle))
    harness.prepare_call(plan, parent["call_id"])
    payload = json.loads(Path(parent["input_path"]).read_text())
    assert payload["child_reports"][0]["report"] == oracle
    assert [d["node_id"] for d in payload["deliveries"]] == ["middle"]
    assert payload["query"]["nodes"] == ["leaf", "middle"]


def test_child_budget_failure_is_not_silently_truncated(plan):
    parent = _call(plan, "02-multilevel", "H", "middle")
    child = _call(plan, "02-multilevel", "H", "leaf")
    harness.prepare_call(plan, child["call_id"])
    Path(child["output_path"]).write_text("x" * 4097)
    harness.prepare_call(plan, parent["call_id"])
    report = json.loads(Path(parent["input_path"]).read_text())["child_reports"][0]
    assert report["transport_error"] == "output_budget_exceeded"
    assert "report" not in report and "raw_output" not in report


def test_real_usage_fields_and_exact_read_result_are_collected(plan, tmp_path):
    call = _call(plan)
    records = _records(plan, call)
    path = _save_rollout(tmp_path, records)
    result = harness.collect_rollout(path, call, plan)
    assert result["passed"]
    assert result["native_token_usage"]["total_tokens"] == 110
    assert result["native_token_usage"]["cached_input_tokens"] == 30
    assert result["peak_request_input_tokens"] == 60
    assert result["input_read_verified"]
    assert result["elapsed_seconds"] == 2
    assert result["rollout_sha256"] == cases.sha(path.read_bytes())


@pytest.mark.parametrize("mutation,code", [
    (lambda r: r[0]["payload"]["source"]["subagent"]["thread_spawn"].update(agent_path="/root/another"), "agent_path_mismatch"),
    (lambda r: r[0]["payload"].update(forked_from_id="old-session"), "not_fresh_session"),
    (lambda r: r[0]["payload"].update(timestamp="2000-01-01T00:00:00+00:00"), "session_before_plan"),
    (lambda r: r[1]["payload"].update(model="other-model"), "model_or_effort_mismatch"),
    (lambda r: r[1]["payload"].update(effort="low"), "model_or_effort_mismatch"),
    (lambda r: r[2]["payload"].update(input='text(await tools.exec_command({"cmd":"cat /private/oracle.json"}));'), "unauthorized_tool_or_read"),
    (lambda r: r[2]["payload"].update(name="read_mcp_resource"), "unauthorized_tool_or_read"),
    (lambda r: r.append(copy.deepcopy(r[2])), "tool_call_count"),
    (lambda r: r[3]["payload"].update(output=json.dumps({"exit_code": 0, "output": "wrong bytes"})), "input_read_unverified"),
    (lambda r: r[3]["payload"].update(output=json.dumps({"exit_code": 1, "output": ""})), "input_read_unverified"),
    (lambda r: r[4]["payload"].update(info=None), "native_token_usage_missing"),
    (lambda r: r[4]["payload"]["info"]["total_token_usage"].update(total_tokens=999), "native_token_usage_inconsistent"),
    (lambda r: r[5]["payload"].update(phase="commentary"), "extra_commentary"),
    (lambda r: r.append(copy.deepcopy(r[5])), "final_count"),
    (lambda r: r.insert(2, r.pop(5)), "final_before_read"),
    (lambda r: r[5].pop("timestamp"), "elapsed_time_unavailable"),
    (lambda r: r[5].update(timestamp="2000-01-01T00:00:00Z"), "elapsed_time_unavailable"),
    (lambda r: r.pop(6), "session_not_complete"),
])
def test_audit_rejects_wrong_native_trace(plan, tmp_path, mutation, code):
    call = _call(plan)
    records = _records(plan, call)
    mutation(records)
    result = harness.collect_rollout(_save_rollout(tmp_path, records), call, plan)
    assert not result["passed"]
    assert code in result["protocol_errors"]


def test_direct_exec_command_equivalent_is_allowed(plan, tmp_path):
    call = _call(plan)
    records = _records(plan, call)
    records[2]["payload"] = {"type": "function_call", "name": "exec_command", "call_id": "read1",
                             "arguments": json.dumps(harness.read_arguments(call["input_path"]))}
    records[3]["payload"]["type"] = "function_call_output"
    records[3]["payload"]["output"] = records[3]["payload"]["output"][1]["text"]
    assert harness.collect_rollout(_save_rollout(tmp_path, records), call, plan)["passed"]


def test_collector_never_relabels_bad_model_answer_as_good(plan, tmp_path):
    call = _call(plan)
    records = _records(plan, call)
    records[5]["payload"]["content"][0]["text"] = '{"status":"full"}'
    result = harness.collect_rollout(_save_rollout(tmp_path, records), call, plan)
    assert not result["passed"]
    assert result["protocol_errors"] == []
    assert not result["quality"]["passed"]


def test_find_rollout_exact_agent_path_and_time_only(plan, tmp_path):
    call = _call(plan)
    records = _records(plan, call)
    p1 = _save_rollout(tmp_path, records, "current.jsonl")
    records[0]["payload"]["timestamp"] = "2000-01-01T00:00:00Z"
    _save_rollout(tmp_path, records, "old.jsonl")
    found = harness.find_rollouts(tmp_path, [call["agent_path"]], plan["created_at"])
    assert found == {call["agent_path"]: [p1]}
    records[0]["payload"]["timestamp"] = plan["created_at"]
    _save_rollout(tmp_path, records, "duplicate.jsonl")
    assert len(harness.find_rollouts(tmp_path, [call["agent_path"]], plan["created_at"])[call["agent_path"]]) == 2


def test_counts_root_and_workers_and_rejects_output_tampering(plan, tmp_path):
    subset = [c for c in plan["calls"] if c["case_id"] == "02-multilevel" and c["strategy"] == "H" and c["repeat"] == 1]
    for index, call in enumerate(subset):
        records = _records(plan, call)
        records[0]["payload"]["id"] = "synthetic-session-{}".format(index)
        harness.collect_rollout(_save_rollout(tmp_path, records, "s{}.jsonl".format(index)), call, plan)
    score = harness.score_plan(plan)
    assert score["strategy_totals"]["H"]["collected_calls"] == 3
    assert score["strategy_totals"]["H"]["native_token_usage"]["total_tokens"] == 330
    assert not score["passed"]  # 其余正式调用未执行，不能把子集包装成完整通过。
    Path(subset[0]["output_path"]).write_text("{}")
    assert harness.score_plan(plan)["integrity_errors"]


def test_prepared_input_cannot_be_changed_after_freeze(plan):
    call = _call(plan)
    harness.prepare_call(plan, call["call_id"])
    Path(call["input_path"]).write_text("{}")
    with pytest.raises(ValueError, match="输入已冻结"):
        harness.prepare_call(plan, call["call_id"])


def test_last_native_total_is_used_once(plan, tmp_path):
    call = _call(plan)
    records = _records(plan, call)
    later = copy.deepcopy(records[4])
    later["payload"]["info"]["total_token_usage"].update(input_tokens=250, output_tokens=50, total_tokens=300)
    records.append(later)
    result = harness.collect_rollout(_save_rollout(tmp_path, records), call, plan)
    assert result["native_token_usage"]["total_tokens"] == 300
    assert result["native_token_usage"]["total_tokens"] != 410


def test_host_required_commentary_before_read_is_allowed(plan, tmp_path):
    call = _call(plan)
    records = _records(plan, call)
    records.insert(2, {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                    "phase": "commentary", "content": [{"type": "output_text", "text": "先读取本次指定输入。"}]}})
    assert harness.collect_rollout(_save_rollout(tmp_path, records), call, plan)["passed"]


def test_all_prepared_calls_fit_budget_and_receive_disjoint_authority(plan):
    # 仅临时测试目录使用人工答案构造依赖；这不是模型证据，不写入正式 evidence。
    sizes = []
    for call in plan["calls"]:
        harness.prepare_call(plan, call["call_id"])
        raw = Path(call["input_path"]).read_bytes()
        sizes.append(len(raw))
        payload = json.loads(raw)
        assert sorted(d["node_id"] for d in payload["deliveries"]) == sorted(call["local_nodes"])
        _, oracle = cases.load_case(call["case_id"])
        Path(call["output_path"]).write_bytes(cases.encode(cases.project_oracle(oracle, call["nodes"])))
    assert max(sizes) <= cases.INPUT_LIMIT


def test_next_step_waits_then_collects_then_prepares(plan, tmp_path):
    result = harness.next_step(plan, tmp_path)
    assert result["action"] == "spawn" and result["index"] == 1
    call = plan["calls"][0]
    records = _records(plan, call)
    path = _save_rollout(tmp_path, records[:-1])
    assert harness.next_step(plan, tmp_path)["action"] == "wait"
    _save_rollout(tmp_path, records)
    result = harness.next_step(plan, tmp_path)
    assert result["action"] == "spawn" and result["index"] == 2
    assert result["collected"][0]["passed"]
    assert result["collected"][0]["elapsed_seconds"] == 2
    assert "final" not in result["collected"][0]
