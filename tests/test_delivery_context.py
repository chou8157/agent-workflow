from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent-workflow" / "scripts"))
import delivery_context
import check_workflow


def test_generate_and_publish_creates_independent_artifact(tmp_path: Path) -> None:
    content = "# 阶段报告\n\n本阶段完成状态模型验证。"
    draft = delivery_context.write_artifact(tmp_path, "report-20260914", "phase_report", "项目负责人", "2026-09-08/2026-09-14", content)

    published = delivery_context.publish_artifact(tmp_path, "report-20260914")

    assert draft.is_file()
    assert published.read_text(encoding="utf-8") == content + "\n"
    metadata = published.with_suffix(".json").read_text(encoding="utf-8")
    assert '"status": "published"' in metadata
    assert '"content_sha256"' in metadata
    assert '"source_snapshot"' in metadata
    assert '"approved_at"' in metadata


@pytest.mark.parametrize("content", ["详见 .agent-workflow/30-records/current-status.md", "W-20260911-workflow-optimization 已完成", "可能已经完成", "token=abc"])
def test_delivery_rejects_internal_or_unconfirmed_content(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError):
        delivery_context.write_artifact(tmp_path, "report", "weekly", "负责人", "2026-W37", content)


def test_published_artifact_cannot_be_overwritten(tmp_path: Path) -> None:
    delivery_context.write_artifact(tmp_path, "report", "weekly", "负责人", "2026-W37", "# 周报")
    delivery_context.publish_artifact(tmp_path, "report")
    delivery_context.write_artifact(tmp_path, "report", "weekly", "负责人", "2026-W37", "# 修订")
    with pytest.raises(ValueError, match="不可原地覆盖"):
        delivery_context.publish_artifact(tmp_path, "report")


def test_check_rejects_tampered_published_content_and_internal_id(tmp_path: Path) -> None:
    delivery_context.write_artifact(tmp_path, "report", "weekly", "负责人", "2026-W37", "# 周报")
    delivery_context.publish_artifact(tmp_path, "report")
    published = tmp_path / ".agent-workflow/30-records/delivery/published/report.md"
    published.write_text("# 周报\nW-secret leaked\n", encoding="utf-8")
    issues = check_workflow.check_project(tmp_path)
    assert any(issue.code == "invalid_delivery_artifact" for issue in issues)


def test_delivery_lifecycle_and_provenance(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("已确认事实\n", encoding="utf-8")
    delivery_context.write_artifact(tmp_path, "v1", "weekly", "负责人", "2026-W37", "# 周报", [source])
    delivery_context.approve_artifact(tmp_path, "v1")
    delivery_context.publish_artifact(tmp_path, "v1")
    delivery_context.write_artifact(tmp_path, "v2", "weekly", "负责人", "2026-W38", "# 新周报")
    delivery_context.publish_artifact(tmp_path, "v2")
    delivery_context.supersede_artifact(tmp_path, "v1", "v2")
    old_meta = (tmp_path / ".agent-workflow/30-records/delivery/published/v1.json").read_text(encoding="utf-8")
    new_meta = (tmp_path / ".agent-workflow/30-records/delivery/published/v2.json").read_text(encoding="utf-8")
    assert '"status": "superseded"' in old_meta
    assert '"supersedes": "v1"' in new_meta
    assert '"sources"' in old_meta
    delivery_context.withdraw_artifact(tmp_path, "v2")
    archived = delivery_context.archive_artifact(tmp_path, "v2")
    assert archived.is_file()
    assert '"status": "archived"' in archived.with_suffix(".json").read_text(encoding="utf-8")
