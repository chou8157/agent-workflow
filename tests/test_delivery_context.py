from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent-workflow" / "scripts"))
import delivery_context


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
