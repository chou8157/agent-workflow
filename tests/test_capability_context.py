import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent-workflow" / "scripts"))
import capability_context


SCRIPT = Path(__file__).parents[1] / "agent-workflow" / "scripts" / "capability_context.py"


def test_dependency_closure_and_profile():
    m = capability_context
    assert m.closure(["delivery"]) == ["core", "evidence", "delivery"]
    assert m.closure(m.PROFILES["minimum"]) == ["core", "work-items"]


def test_enable_is_non_destructive(tmp_path):
    m = capability_context
    root = tmp_path / ".agent-workflow"
    root.mkdir()
    existing = root / "README.md"
    existing.write_text("用户内容\n", encoding="utf-8")
    added = m.enable(tmp_path, ["delivery"])
    assert added == ["core", "evidence", "delivery"]
    assert existing.read_text(encoding="utf-8") == "用户内容\n"
    state = json.loads((root / ".capabilities.json").read_text(encoding="utf-8"))
    assert state["enabled"] == added


def test_unknown_capability_rejected(tmp_path):
    m = capability_context
    try:
        m.enable(tmp_path, ["unknown"])
    except ValueError as exc:
        assert "未知能力" in str(exc)
    else:
        raise AssertionError("应拒绝未知能力")


def test_scaffold_capability_includes_dependencies(tmp_path):
    import scaffold_workflow
    scaffold_workflow.scaffold_project(tmp_path, capabilities=["delivery"])
    state = json.loads((tmp_path / ".agent-workflow" / ".capabilities.json").read_text(encoding="utf-8"))
    assert state["enabled"] == ["core", "evidence", "delivery"]
