"""隔离副本试跑的来源保护、脱敏和真实 CLI 路径验证。"""

import json
from pathlib import Path
import shutil

import pytest

from experiments.frontier import node_workflow, real_project_trial as trial
from experiments.frontier.test_mvp_light import FIXTURES


def _sources(tmp_path):
    root = tmp_path / "private-projects"
    shutil.copytree(FIXTURES / "nodes", root)
    return {role: root / role for role in trial.ROLES}


def test_copy_excludes_code_configuration_and_unrelated_workflow_documents(tmp_path):
    sources = _sources(tmp_path)
    source = sources["root"]
    (source / "secret.env").write_text("DO_NOT_COPY_SECRET", encoding="utf-8")
    (source / "application.py").write_text("PRIVATE_CODE", encoding="utf-8")
    (source / ".agent-workflow" / "unrelated.md").write_text("PRIVATE_UNRELATED_NOTE", encoding="utf-8")
    destination = tmp_path / "copy"

    counts = trial._copy_workflow(source, destination)

    assert counts["work_items"] == 1
    assert not (destination / "secret.env").exists()
    assert not (destination / "application.py").exists()
    assert not (destination / ".agent-workflow" / "unrelated.md").exists()
    assert all(path.suffix in (".md", ".json") for path in destination.rglob("*") if path.is_file())
    assert not list(destination.rglob(".frontier-node.json"))


def test_copy_includes_explicit_workflow_evidence_but_does_not_follow_symlinks(tmp_path):
    sources = _sources(tmp_path)
    source = sources["root"]
    item = next((source / node_workflow.ITEMS).glob("W-*"))
    proof = source / ".agent-workflow" / "proof.md"
    proof.write_text("独立证据\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("禁止复制的外部内容", encoding="utf-8")
    (source / ".agent-workflow" / "linked.md").symlink_to(outside)
    state_path = item / ".state.json"
    state = json.loads(state_path.read_bytes())
    state["activity_records"] = [{"evidence_refs": [{"path": ".agent-workflow/proof.md"},
                                                    {"path": ".agent-workflow/linked.md"}]}]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    destination = tmp_path / "copy"

    trial._copy_workflow(source, destination)

    assert (destination / ".agent-workflow" / "proof.md").read_bytes() == proof.read_bytes()
    assert not (destination / ".agent-workflow" / "linked.md").exists()


def test_output_inside_source_is_rejected_before_any_source_mutation(tmp_path):
    sources = _sources(tmp_path)
    before = {role: trial._manifest(source) for role, source in sources.items()}
    with pytest.raises(ValueError, match="所有来源项目之外"):
        trial.run_trial(sources, sources["root"] / "report.json")
    assert {role: trial._manifest(source) for role, source in sources.items()} == before
    assert not (sources["root"] / "report.json").exists()


def test_sources_must_be_explicit_distinct_projects(tmp_path):
    sources = _sources(tmp_path)
    with pytest.raises(ValueError, match="显式指定"):
        trial.run_trial({"root": sources["root"]}, tmp_path / "report.json")
    with pytest.raises(ValueError, match="不同项目"):
        trial.run_trial({role: sources["root"] for role in trial.ROLES}, tmp_path / "report.json")


def test_complete_trial_preserves_sources_and_redacts_business_content(tmp_path):
    sources = _sources(tmp_path)
    private_text = "PRIVATE_BUSINESS_TITLE_SHOULD_NOT_LEAK"
    for source in sources.values():
        item = next((source / node_workflow.ITEMS).glob("W-*"))
        state_path = item / ".state.json"
        state = json.loads(state_path.read_bytes())
        state["title"] = private_text
        state_path.write_text(json.dumps(state), encoding="utf-8")
    leaf_state = next((sources["leaf"] / node_workflow.ITEMS).glob("W-*")) / ".state.json"
    leaf_state.unlink()
    before = {role: trial._manifest(source) for role, source in sources.items()}
    output = tmp_path / "safe-evidence" / "report.json"

    result = trial.run_trial(sources, output)

    assert result["status"] == "passed", result["checks"]
    assert result["failure_type"] is None
    assert all(result["checks"].values())
    assert result["historical_baseline"]["status"] == "partial"
    assert result["historical_baseline"]["activity_count"] == 0
    assert result["historical_baseline"]["unknown_work_item_count"] == 3
    assert result["sources"]["leaf"]["missing_state"] == 1
    assert [result["hierarchical_reports"][role]["trial_activity_count"] for role in trial.ROLES] == [3, 2, 1]
    assert {role: trial._manifest(source) for role, source in sources.items()} == before
    serialized = output.read_text(encoding="utf-8")
    assert private_text not in serialized
    assert str(tmp_path) not in serialized
    assert "/Users/" not in serialized and "/private/tmp/" not in serialized
    assert "W-2026" not in serialized
    assert json.loads(serialized) == result
    assert {command["command"] for command in result["commands"]} == {"connect", "record", "report", "leave"}
