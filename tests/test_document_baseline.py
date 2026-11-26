from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent-workflow" / "scripts"))
import document_baseline
import scaffold_workflow
import unified_upgrade


def test_baseline_requires_known_template_source(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    (tmp_path / "AGENTS.md").write_text((tmp_path / "AGENTS.md").read_text(encoding="utf-8") + "\n用户规则\n", encoding="utf-8")
    plan = document_baseline.build_plan(tmp_path)
    assert plan["status"] == "review"
    assert plan["review"] and not plan["conflicts"]
    assert not (tmp_path / document_baseline.BASELINE_FILE).exists()


def test_three_way_merge_preserves_user_change_when_template_changes_elsewhere() -> None:
    base = "标题\n\n受管理规则\n"
    current = "用户标题\n\n受管理规则\n"
    target = "标题\n\n受管理规则\n新增规则\n"
    result = document_baseline.three_way_merge(base, current, target)
    assert result["status"] == "merged"
    assert result["content"] == "用户标题\n\n受管理规则\n新增规则\n"


def test_three_way_merge_marks_overlapping_changes() -> None:
    result = document_baseline.three_way_merge("原文\n", "当前修改\n", "模板修改\n")
    assert result["status"] == "conflict"
    assert "<<<<<<< 当前项目" in result["content"]
    assert result["conflicts"]


def test_unified_project_apply_records_transaction_and_baseline(tmp_path: Path) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    plan = unified_upgrade.build_plan(project=tmp_path)
    result = unified_upgrade.apply_plan(plan, tmp_path, None, None, False, True, False)
    assert result["results"]["project"]["transaction_status"] == "committed"
    assert (tmp_path / document_baseline.BASELINE_FILE).is_file()
    assert not document_baseline.build_plan(tmp_path)["conflicts"]
    assert any(path.name == "journal.json" for path in (tmp_path / ".agent-workflow/.upgrade-transactions" / result["results"]["project"]["transaction"]).iterdir())


def test_project_transaction_failure_restores_write_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scaffold_workflow.scaffold_project(tmp_path)
    plan = unified_upgrade.build_plan(project=tmp_path)
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def fail(*_args, **_kwargs):
        raise RuntimeError("模拟项目升级中断")

    monkeypatch.setattr(document_baseline, "apply_plan", fail)
    with pytest.raises(RuntimeError, match="模拟项目升级中断"):
        unified_upgrade.apply_plan(plan, tmp_path, None, None, False, True, False)
    after = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file() and ".upgrade-transactions" not in path.parts and path.name not in (".upgrade-transaction.lock", ".upgrade.lock")}
    assert after == before
    assert not document_baseline.read_baseline(tmp_path)
    assert not document_baseline.build_plan(tmp_path)["conflicts"]
