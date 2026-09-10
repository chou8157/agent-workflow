from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "agent-workflow" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_workflow
import scaffold_workflow
import task_context
import upgrade_workflow


def test_scaffold_creates_work_items_entry(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)

    assert (tmp_path / ".agent-workflow" / "30-records" / "work-items" / "README.md").is_file()
    assert (tmp_path / ".agent-workflow" / "WORKFLOW_VERSION").read_text(encoding="utf-8") == f"{upgrade_workflow.LATEST_VERSION}\n"


def test_create_list_and_update_work_item(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)

    created = task_context.create_work_item(tmp_path, "W-payment", "支付需求", "需求", "")

    assert (created / "README.md").is_file()
    assert (created / "current-status.md").is_file()
    assert (created / "progress" / "README.md").is_file()
    assert task_context.list_work_items(tmp_path) == [
        {
            "id": "W-payment",
            "title": "支付需求",
            "type": "需求",
            "status": "planned",
            "parent": "无",
            "path": str(created),
        }
    ]

    task_context.set_status(tmp_path, "W-payment", "in_progress")

    assert task_context.get_work_item(tmp_path, "W-payment")["status"] == "in_progress"


def test_invalid_work_item_id_is_rejected(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)

    try:
        task_context.create_work_item(tmp_path, "payment", "支付需求", "需求", "")
    except ValueError as error:
        assert "必须以 W- 开头" in str(error)
    else:
        raise AssertionError("应拒绝不合法的工作项 ID")


def test_create_restores_missing_work_items_entry(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    work_items = tmp_path / ".agent-workflow" / "30-records" / "work-items"
    for path in sorted(work_items.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    work_items.rmdir()

    created = task_context.create_work_item(tmp_path, "W-recover", "补齐入口", "任务", "")

    assert (work_items / "README.md").is_file()
    assert created.is_dir()


def test_legacy_workflow_is_valid_without_work_items(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    work_items = tmp_path / ".agent-workflow" / "30-records" / "work-items"
    for path in sorted(work_items.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    work_items.rmdir()

    assert check_workflow.check_project(tmp_path) == []
    strict_issues = check_workflow.check_project(tmp_path, require_work_items=True)
    assert [issue.code for issue in strict_issues] == ["missing_work_items"]


def test_safe_upgrade_preserves_existing_entry_documents(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    workflow = tmp_path / ".agent-workflow"
    work_items = workflow / "30-records" / "work-items"
    for path in sorted(work_items.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    work_items.rmdir()
    (workflow / "WORKFLOW_VERSION").unlink()

    agents = tmp_path / "AGENTS.md"
    readme = workflow / "README.md"
    disclosure = workflow / "00-core" / "disclosure.md"
    agents.write_text("# 既有入口\n", encoding="utf-8")
    readme.write_text("# 既有工作流\n", encoding="utf-8")
    disclosure.write_text("# 既有渐进规则\n", encoding="utf-8")

    plan = upgrade_workflow.build_upgrade_plan(tmp_path)
    assert plan["current_version"] == 1
    assert len(plan["safe_actions"]) == 2
    assert len(plan["review_actions"]) == 3

    result = upgrade_workflow.apply_safe_upgrade(tmp_path)

    assert (work_items / "README.md").is_file()
    assert (workflow / "WORKFLOW_VERSION").read_text(encoding="utf-8") == "2\n"
    assert agents.read_text(encoding="utf-8") == "# 既有入口\n"
    assert readme.read_text(encoding="utf-8") == "# 既有工作流\n"
    assert disclosure.read_text(encoding="utf-8") == "# 既有渐进规则\n"
    assert len(result["created_suggestions"]) == 3
    assert len(result["review_actions"]) == 3


def test_upgrade_repairs_missing_structure_at_latest_version(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    workflow = tmp_path / ".agent-workflow"
    work_items = workflow / "30-records" / "work-items"
    for path in sorted(work_items.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    work_items.rmdir()

    plan = upgrade_workflow.build_upgrade_plan(tmp_path)
    assert plan["current_version"] == upgrade_workflow.LATEST_VERSION
    assert [action["action"] for action in plan["safe_actions"]] == ["copy_template"]

    result = upgrade_workflow.apply_safe_upgrade(tmp_path)

    assert (work_items / "README.md").is_file()
    assert result["up_to_date"] is True
