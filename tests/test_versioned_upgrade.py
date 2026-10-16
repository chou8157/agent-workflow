from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "agent-workflow/scripts"
sys.path.insert(0, str(SCRIPTS))
import check_workflow
import scaffold_workflow
import task_context
import upgrade_workflow


def snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


def legacy_item(root: Path, item_id: str = "W-old", status: str = "in_progress") -> Path:
    item = root / ".agent-workflow/30-records/work-items" / item_id
    item.mkdir(parents=True, exist_ok=True)
    (item / "work-item.md").write_text(
        f"# 历史业务任务\n\n- ID：`{item_id}`\n- 标题：保留用户任务\n- 类型：需求\n- 状态：{status}\n- 父工作项：无\n\n原始需求与自定义内容。\n",
        encoding="utf-8",
    )
    return item


def project_with_version(root: Path, version: int | None) -> Path:
    scaffold_workflow.scaffold_project(root)
    workflow = root / ".agent-workflow"
    version_path = workflow / "WORKFLOW_VERSION"
    if version is None:
        version_path.unlink()
    else:
        version_path.write_text(f"{version}\n", encoding="utf-8")
    if version is None or version < 5:
        (workflow / ".capabilities.json").unlink()
    if version is None or version < 6:
        (workflow / "00-core/versioning.md").unlink(missing_ok=True)
        for path in (root / "AGENTS.md", workflow / "README.md", workflow / "00-core/workflow.md"):
            path.write_text(path.read_text(encoding="utf-8").replace(upgrade_workflow.V6_MARKER, ""), encoding="utf-8")
    return root


@pytest.mark.parametrize("version", [None, 1, 2, 3, 4, 5, 6])
def test_every_supported_version_upgrades_without_reinitializing(tmp_path: Path, version: int | None) -> None:
    project_with_version(tmp_path, version)
    item = legacy_item(tmp_path, status="completed")
    before = snapshot(tmp_path)
    plan = upgrade_workflow.build_upgrade_plan(tmp_path)
    assert plan["version_path"] == list(range(version or 1, 7))
    assert plan["version_source"] == ("file" if version else "legacy_unversioned")
    assert plan["migration_pending"] and not plan["up_to_date"]
    assert snapshot(tmp_path) == before

    result = upgrade_workflow.apply_safe_upgrade(tmp_path)

    assert result["applied"] and result["structure_up_to_date"] and result["runtime_ready"]
    assert not result["migration_pending"] and not result["conflicts"]
    assert (tmp_path / ".agent-workflow/WORKFLOW_VERSION").read_text() == "6\n"
    assert (tmp_path / ".agent-workflow/00-core/versioning.md").is_file()
    for rel, digest in before.items():
        if rel != ".agent-workflow/WORKFLOW_VERSION":
            assert hashlib.sha256((tmp_path / rel).read_bytes()).hexdigest() == digest
    state = task_context.read_state(item)
    assert state["status"] == "completed"
    assert state["created_at"] is None and state["completed_at"] is None
    assert state["completed_at_unknown"] is True
    assert "activity_records" not in state
    assert not (tmp_path / ".agent-workflow/frontier").exists()
    assert not (tmp_path / ".agent-workflow/30-records/delivery").exists()
    assert check_workflow.check_project(tmp_path, require_work_items=True) == []
    after = snapshot(tmp_path)
    repeated = upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert repeated["migrated_states"] == [] and repeated["created_suggestions"] == []
    assert snapshot(tmp_path) == after


def test_latest_structure_does_not_hide_missing_state_or_review(tmp_path: Path) -> None:
    project_with_version(tmp_path, 6)
    legacy_item(tmp_path)
    plan = upgrade_workflow.build_upgrade_plan(tmp_path)
    assert plan["structure_up_to_date"]
    assert plan["migration_pending"] and not plan["runtime_ready"] and not plan["up_to_date"]
    result = upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert result["up_to_date"]


@pytest.mark.parametrize("version", ["0", "-1", "7", "1.0", "abc", "", "01", "１"])
def test_invalid_or_future_version_never_writes(tmp_path: Path, version: str) -> None:
    project_with_version(tmp_path, 5)
    (tmp_path / ".agent-workflow/WORKFLOW_VERSION").write_text(version, encoding="utf-8")
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("bad_kind", ["blocked", "status", "missing_title", "duplicate", "wrong_id", "invalid_json", "existing_conflict", "bad_capabilities"])
def test_preflight_blockers_leave_entire_project_unchanged(tmp_path: Path, bad_kind: str) -> None:
    project_with_version(tmp_path, 2)
    legacy_item(tmp_path, "W-a-valid")
    item = legacy_item(tmp_path, "W-z-bad")
    path = item / "work-item.md"
    content = path.read_text(encoding="utf-8")
    if bad_kind == "blocked":
        content = content.replace("in_progress", "blocked")
    elif bad_kind == "status":
        content = content.replace("in_progress", "finished")
    elif bad_kind == "missing_title":
        content = content.replace("保留用户任务", "")
    elif bad_kind == "duplicate":
        content += "\n- 状态：completed\n"
    elif bad_kind == "wrong_id":
        content = content.replace("`W-z-bad`", "`W-other`")
    elif bad_kind == "invalid_json":
        (item / ".state.json").write_text("{}", encoding="utf-8")
    elif bad_kind == "existing_conflict":
        state = task_context.legacy_state_payload(item)
        state.pop("legacy_metadata")
        state["status"] = "planned"
        task_context.write_json_atomic(item / ".state.json", state)
    else:
        (tmp_path / ".agent-workflow/.capabilities.json").write_text('{"enabled":["future-capability"]}', encoding="utf-8")
    path.write_text(content, encoding="utf-8")
    before = snapshot(tmp_path)
    plan = upgrade_workflow.build_upgrade_plan(tmp_path)
    assert plan["conflicts"] and not plan["can_apply"] and not plan["up_to_date"]
    result = upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert result["applied"] is False
    assert snapshot(tmp_path) == before


def test_blocked_reason_migrates_and_legacy_snapshot_does_not_become_live_state(tmp_path: Path) -> None:
    project_with_version(tmp_path, 3)
    item = legacy_item(tmp_path, status="blocked")
    path = item / "work-item.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n- 阻塞原因：等待接口\n", encoding="utf-8")
    result = upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert result["runtime_ready"]
    assert task_context.read_state(item)["blocked_reason"] == "等待接口"
    task_context.set_status(tmp_path, item.name, "in_progress")
    assert task_context.migration_report(tmp_path) == []
    path.write_text(path.read_text(encoding="utf-8").replace("blocked", "archived"), encoding="utf-8")
    assert "冲突" in task_context.migration_report(tmp_path)[0]["finding"]


@pytest.mark.parametrize("link_kind", ["core", "work_item", "state", "metadata", "suggestion"])
def test_symlink_escape_is_rejected_without_writing(tmp_path: Path, link_kind: str) -> None:
    project = project_with_version(tmp_path / "project", 3)
    outside = tmp_path / "outside"
    outside.mkdir()
    item = legacy_item(project)
    if link_kind == "core":
        target = project / ".agent-workflow/00-core/versioning.md"
        destination = outside / "rules.md"
    elif link_kind == "work_item":
        target = item.parent / "W-link"
        destination = outside
    elif link_kind == "state":
        target, destination = item / ".state.json", outside / "state.json"
    elif link_kind == "metadata":
        target, destination = item / "work-item.md", outside / "source.md"
        target.rename(destination)
    else:
        target = upgrade_workflow.suggestion_path(project / "AGENTS.md")
        destination = outside / "suggestion.md"
    target.symlink_to(destination)
    before = snapshot(tmp_path)
    result = upgrade_workflow.apply_safe_upgrade(project)
    assert not result["applied"] and result["conflicts"]
    assert snapshot(tmp_path) == before


def test_interrupted_upgrade_is_restartable_and_version_is_written_last(tmp_path: Path, monkeypatch) -> None:
    project_with_version(tmp_path, 2)
    item = legacy_item(tmp_path)
    original_write = upgrade_workflow.write_atomic
    calls = 0

    def stop_after_first_write(path, content, replace=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("模拟升级中断")
        return original_write(path, content, replace)

    monkeypatch.setattr(upgrade_workflow, "write_atomic", stop_after_first_write)
    with pytest.raises(ValueError, match="模拟升级中断"):
        upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert (tmp_path / ".agent-workflow/WORKFLOW_VERSION").read_text() == "2\n"
    assert not (item / ".state.json").exists()
    monkeypatch.setattr(upgrade_workflow, "write_atomic", original_write)
    assert upgrade_workflow.apply_safe_upgrade(tmp_path)["runtime_ready"]
    assert task_context.read_state(item)["status"] == "in_progress"


def test_document_reviews_are_real_paths_and_do_not_prevent_state_reading(tmp_path: Path) -> None:
    project_with_version(tmp_path, 1)
    legacy_item(tmp_path)
    result = upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert result["runtime_ready"] and result["review_pending"] and not result["up_to_date"]
    assert len(result["created_suggestions"]) == 3
    for review in result["review_actions"]:
        path = Path(review["suggestion"])
        assert path.relative_to(tmp_path) and path.is_file()
    assert not any(path.name.startswith("请先运行") for path in tmp_path.rglob("*"))


def test_old_optional_modules_are_preserved_without_enabling_absent_modules(tmp_path: Path) -> None:
    project_with_version(tmp_path, 4)
    delivery = tmp_path / ".agent-workflow/30-records/delivery"
    delivery.mkdir()
    (delivery / "user-history.md").write_text("原有交付内容", encoding="utf-8")
    result = upgrade_workflow.apply_safe_upgrade(tmp_path)
    enabled = json.loads((tmp_path / ".agent-workflow/.capabilities.json").read_text())["enabled"]
    assert result["runtime_ready"] and "delivery" in enabled and "evidence" in enabled
    assert "shared-workflow" not in enabled and "audit" not in enabled
    assert (delivery / "user-history.md").read_text(encoding="utf-8") == "原有交付内容"


def test_cli_read_only_and_blocker_exit_code(tmp_path: Path) -> None:
    project_with_version(tmp_path, 5)
    legacy_item(tmp_path, status="blocked")
    before = snapshot(tmp_path)
    result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "upgrade_workflow.py"), str(tmp_path), "status", "--json"], capture_output=True, text=True)
    assert result.returncode == 1
    assert not json.loads(result.stdout)["can_apply"]
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("profile", ["minimum", "standard", "advanced"])
def test_existing_profiles_upgrade_and_pass_workflow_check(tmp_path: Path, profile: str) -> None:
    scaffold_workflow.scaffold_project(tmp_path, profile=profile)
    workflow = tmp_path / ".agent-workflow"
    (workflow / "WORKFLOW_VERSION").write_text("5\n", encoding="utf-8")
    (workflow / "00-core/versioning.md").unlink()
    manifest = (workflow / ".capabilities.json").read_bytes()
    result = upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert result["structure_up_to_date"] and result["runtime_ready"]
    assert (workflow / ".capabilities.json").read_bytes() == manifest
    assert check_workflow.check_project(tmp_path, require_work_items=True) == []


def test_latest_version_repairs_declared_capability_dependencies_and_missing_files(tmp_path: Path) -> None:
    project_with_version(tmp_path, 6)
    manifest = tmp_path / ".agent-workflow/.capabilities.json"
    manifest.write_text(json.dumps({"version": 1, "enabled": ["core", "work-items", "delivery"], "custom": "preserved"}), encoding="utf-8")
    plan = upgrade_workflow.build_upgrade_plan(tmp_path)
    assert not plan["up_to_date"] and not plan["structure_up_to_date"]
    result = upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert result["up_to_date"]
    data = json.loads(manifest.read_text())
    assert "evidence" in data["enabled"] and data["custom"] == "preserved"
    assert check_workflow.check_project(tmp_path, require_work_items=True) == []


def test_restart_after_state_migration_preserves_migration_timestamp(tmp_path: Path, monkeypatch) -> None:
    project_with_version(tmp_path, 2)
    item = legacy_item(tmp_path)
    original_write = upgrade_workflow.write_atomic

    def stop_before_version(path, content, replace=False):
        if path.name == "WORKFLOW_VERSION":
            raise OSError("模拟版本标记前中断")
        return original_write(path, content, replace)

    monkeypatch.setattr(upgrade_workflow, "write_atomic", stop_before_version)
    with pytest.raises(ValueError, match="模拟版本标记前中断"):
        upgrade_workflow.apply_safe_upgrade(tmp_path)
    before = (item / ".state.json").read_bytes()
    assert (tmp_path / ".agent-workflow/WORKFLOW_VERSION").read_text() == "2\n"
    monkeypatch.setattr(upgrade_workflow, "write_atomic", original_write)
    result = upgrade_workflow.apply_safe_upgrade(tmp_path)
    assert result["runtime_ready"] and result["migrated_states"] == []
    assert (item / ".state.json").read_bytes() == before


def test_concurrent_upgrades_share_project_and_state_locks(tmp_path: Path) -> None:
    project_with_version(tmp_path, 2)
    legacy_item(tmp_path)
    command = [sys.executable, "-B", str(SCRIPTS / "upgrade_workflow.py"), str(tmp_path), "apply-safe", "--json"]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout))
    assert sum(len(result["migrated_states"]) for result in results) == 1
    assert all(result["structure_up_to_date"] and result["runtime_ready"] for result in results)
    assert task_context.migration_report(tmp_path) == []
