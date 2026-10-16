"""activity_records 迁移 dry-run 的只读边界测试。"""

import json
from pathlib import Path

import pytest

from experiments.frontier import activity_migration_dry_run as migration
from experiments.frontier.activity_migration_dry_run import scan_project
from experiments.frontier.coordinator import _read_bytes, SourceReadError


def _project(tmp_path):
    item = tmp_path / ".agent-workflow/30-records/work-items/W-test"
    (item / "progress").mkdir(parents=True)
    (item / ".state.json").write_text(json.dumps({
        "id": "W-test", "title": "测试", "type": "需求", "status": "in_progress",
        "parent": None, "created_at": None, "updated_at": "2026-10-14T10:00:00+08:00",
        "completed_at": None, "activity_records": [],
    }, ensure_ascii=False), encoding="utf-8")
    (item / "work-item.md").write_text("# 测试\n", encoding="utf-8")
    (item / "current-status.md").write_text("## 2026-10-14 状态更新\n", encoding="utf-8")
    (item / "validation-log.md").write_text("## 2026-10-13 - 验证\n", encoding="utf-8")
    (item / "progress/001.md").write_text("## 日期\n2026-10-12\n", encoding="utf-8")
    return tmp_path


def test_dry_run_marks_log_dates_as_candidates_and_status_dates_as_ignored(tmp_path):
    result = scan_project(_project(tmp_path))

    assert result["status"] == "full"
    assert result["activity_record_count"] == 0
    assert result["candidate_record_dates"] == ["2026-10-12", "2026-10-13"]
    item = result["work_items"][0]
    assert item["ignored_status_dates"][0]["date"] == "2026-10-14"
    assert all(candidate["requires_confirmation"] for candidate in item["candidate_record_dates"])


def test_dry_run_reports_missing_work_item_documents(tmp_path):
    project = _project(tmp_path)
    (project / ".agent-workflow/30-records/work-items/W-test/current-status.md").unlink()

    result = scan_project(project)

    assert result["status"] == "partial"
    assert result["work_items"][0]["missing_documents"] == ["current-status.md"]


def test_dates_keep_exact_location_hash_and_ignore_examples(tmp_path):
    project = _project(tmp_path)
    item = project / migration.WORK_ITEMS / "W-test"
    (item / "validation-log.md").write_text(
        "## 2026-10-13 完成验证\n## 2026-10-12：记录\n"
        "```markdown\n## 2026-10-11 示例\n```\n"
        "## 2026-02-30 无效\n## 2026-10-10abc\n", encoding="utf-8")
    before = {str(path): path.read_bytes() for path in project.rglob("*") if path.is_file()}

    result = scan_project(project)

    assert result == scan_project(project)
    assert before == {str(path): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    dates = result["work_items"][0]["candidate_record_dates"]
    assert [(d["source"], d["line"], d["date"]) for d in dates] == [
        ("validation-log.md", 1, "2026-10-13"), ("validation-log.md", 2, "2026-10-12"),
        ("progress/001.md", 2, "2026-10-12"),
    ]
    for candidate in dates:
        source = next(s for s in result["sources"] if s["path"].endswith("/" + candidate["source"]))
        assert candidate["source_sha256"] == source["sha256"]


@pytest.mark.parametrize("damage", ["array", "status", "id", "date", "duplicate_activity", "duplicate_key", "deep_json"])
def test_invalid_state_or_activity_is_partial_not_valid_coverage(tmp_path, damage):
    project = _project(tmp_path)
    path = project / migration.WORK_ITEMS / "W-test/.state.json"
    state = json.loads(path.read_text())
    activity = {"id": "a1", "date": "2026-10-14", "summary": "完成验证", "status": "completed"}
    state["activity_records"] = [activity]
    if damage == "array":
        state = []
    elif damage == "status":
        state["status"] = "shipped"
    elif damage == "id":
        state["id"] = "W-elsewhere"
    elif damage == "date":
        activity["date"] = "2026-02-30"
    elif damage == "duplicate_activity":
        state["activity_records"].append(activity)
    content = json.dumps(state, ensure_ascii=False)
    if damage == "duplicate_key":
        content = content[:-1] + ', "status": "planned"}'
    elif damage == "deep_json":
        content = "[" * 2000 + "0" + "]" * 2000
    path.write_text(content, encoding="utf-8")

    result = scan_project(project)

    assert result["status"] == "partial"
    assert result["work_items"][0]["invalid_state"]
    assert result["work_items"][0]["state_format"] == "invalid"
    assert result["work_items_with_activity_records"] == 0


def test_legacy_format_is_distinct_from_invalid_json(tmp_path, capsys):
    project = _project(tmp_path)
    (project / migration.WORK_ITEMS / "W-test/.state.json").unlink()

    result = scan_project(project)

    assert result["status"] == "partial"
    assert result["work_items"][0]["state_format"] == "legacy_unmigrated_candidate"
    assert result["work_items"][0]["invalid_state"] is None
    assert migration.main([str(project), "--json"]) == 2
    assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize("location", ["workflow", "item", "progress", "document"])
def test_symlinks_are_explicit_gaps_without_reading_targets(tmp_path, monkeypatch, location):
    project = _project(tmp_path / "project")
    item = project / migration.WORK_ITEMS / "W-test"
    path = {"workflow": project / ".agent-workflow", "item": item,
            "progress": item / "progress", "document": item / "validation-log.md"}[location]
    target = tmp_path / "outside"
    path.rename(target)
    path.symlink_to(target, target_is_directory=target.is_dir())
    reads = []
    real_read = migration._read_bytes

    def recording_read(path, **kwargs):
        assert target not in path.resolve().parents and path.resolve() != target
        reads.append(path)
        return real_read(path, **kwargs)

    monkeypatch.setattr(migration, "_read_bytes", recording_read)
    result = scan_project(project)
    assert result["status"] in {"failed", "partial"}
    assert result["issues"] or result["work_items"][0]["issues"]
    if location in {"workflow", "item"}:
        assert not reads


@pytest.mark.parametrize("failure", ["permission", "encoding"])
def test_unreadable_date_document_retains_gap(tmp_path, monkeypatch, failure):
    project = _project(tmp_path)
    path = project / migration.WORK_ITEMS / "W-test/validation-log.md"
    if failure == "encoding":
        path.write_bytes(b"\xff")
    else:
        real_read = migration._read_bytes

        def denied_read(requested, **kwargs):
            if requested == path:
                raise PermissionError("测试拒绝读取")
            return real_read(requested, **kwargs)

        monkeypatch.setattr(migration, "_read_bytes", denied_read)
    result = scan_project(project)
    assert result["status"] == "partial"
    assert any(issue["source"].endswith("validation-log.md") for issue in result["work_items"][0]["issues"])


def test_optional_document_disappearing_during_read_is_not_silently_ignored(tmp_path, monkeypatch):
    project = _project(tmp_path)
    path = project / migration.WORK_ITEMS / "W-test/validation-log.md"
    real_read = migration._read_bytes

    def disappearing_read(requested, **kwargs):
        if requested == path:
            path.unlink()
        return real_read(requested, **kwargs)

    monkeypatch.setattr(migration, "_read_bytes", disappearing_read)
    result = scan_project(project)
    assert result["status"] == "partial"
    assert "validation-log.md" in result["work_items"][0]["missing_documents"]


def test_scan_budgets_explicitly_mark_incomplete_results(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(migration, "MAX_DATE_LOCATIONS", 1)
    result = scan_project(project)
    assert result["status"] == "partial"
    assert result["candidate_record_date_count"] == 1
    monkeypatch.setattr(migration, "MAX_TOTAL_BYTES", 20)
    result = scan_project(project)
    assert result["status"] == "partial"
    assert result["read_metrics"]["bytes_read"] <= 20
    monkeypatch.setattr(migration, "MAX_DIRECTORY_ENTRIES", 0)
    assert scan_project(project)["status"] == "failed"


def test_safe_reader_bounds_actual_read_bytes(tmp_path):
    path = tmp_path / "large.md"
    path.write_bytes(b"a" * 100)
    with pytest.raises(SourceReadError) as error:
        _read_bytes(path, max_bytes=10)
    assert error.value.bytes_read == 11


def test_activity_coverage_is_counted_per_work_item(tmp_path):
    project = _project(tmp_path)
    item = project / migration.WORK_ITEMS / "W-test"
    other = item.with_name("W-other")
    other.mkdir()
    for name in (".state.json", "work-item.md", "current-status.md"):
        (other / name).write_bytes((item / name).read_bytes())
    state = json.loads((other / ".state.json").read_text())
    state["id"] = "W-other"
    state["activity_records"] = [{"id": "a1", "date": "2026-10-14", "summary": "完成验证", "status": "completed"}]
    (other / ".state.json").write_text(json.dumps(state), encoding="utf-8")

    result = scan_project(project)

    assert result["status"] == "full"
    assert result["work_items_with_activity_records"] == 1
    assert result["work_items_without_confirmed_activity_records"] == ["W-test"]
