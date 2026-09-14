from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent-workflow" / "scripts"))
import scaffold_workflow
import task_context
import finalize_context


def test_finalize_records_facts_idempotently(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    task_context.create_work_item(tmp_path, "W-finalize", "收口", "任务", "")
    task_context.set_status(tmp_path, "W-finalize", "in_progress")
    result = finalize_context.finalize(tmp_path, "W-finalize", summary="完成实现", tests=["pytest tests -q"])
    assert result["recorded"] is True
    assert len(list((tmp_path / ".agent-workflow/30-records/work-items/W-finalize/progress").glob("*.md"))) == 2
    assert "最近收口：完成实现" in (tmp_path / ".agent-workflow/30-records/work-items/W-finalize/current-status.md").read_text(encoding="utf-8")
    again = finalize_context.finalize(tmp_path, "W-finalize", summary="完成实现", tests=["pytest tests -q"])
    assert again["recorded"] is False


def test_finalize_does_not_infer_completion(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    task_context.create_work_item(tmp_path, "W-finalize", "收口", "任务", "")
    task_context.set_status(tmp_path, "W-finalize", "in_progress")
    result = finalize_context.finalize(tmp_path, "W-finalize", summary="已完成")
    assert result["pending_confirmation"]
    assert task_context.read_state(tmp_path / ".agent-workflow/30-records/work-items/W-finalize")["status"] == "in_progress"
