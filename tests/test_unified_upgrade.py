from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from experiments.frontier import build_release as release


SCRIPTS = Path(__file__).resolve().parents[1] / "agent-workflow" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import scaffold_workflow  # noqa: E402
import task_context  # noqa: E402
import unified_upgrade  # noqa: E402
import upgrade_workflow  # noqa: E402


def _project(root: Path, version: int = 5) -> Path:
    scaffold_workflow.scaffold_project(root)
    (root / ".agent-workflow/WORKFLOW_VERSION").write_text(f"{version}\n", encoding="utf-8")
    if version < 6:
        (root / ".agent-workflow/00-core/versioning.md").unlink(missing_ok=True)
        marker = upgrade_workflow.V6_MARKER
        for path in (root / "AGENTS.md", root / ".agent-workflow/README.md", root / ".agent-workflow/00-core/workflow.md"):
            path.write_text(path.read_text(encoding="utf-8").replace(marker, ""), encoding="utf-8")
    return root


@pytest.fixture
def package(tmp_path: Path) -> Path:
    destination = tmp_path / "package"
    release.build(destination)
    return destination


def test_combined_plan_is_read_only_and_reports_project_pending(tmp_path: Path, package: Path) -> None:
    project = _project(tmp_path / "project")
    skills_root = tmp_path / "skills"
    release.install(package, skills_root)
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    plan = unified_upgrade.build_plan(project, package, skills_root)
    summary = unified_upgrade.summarize(plan)

    assert summary["status"] == "pending"
    assert summary["pending"] == ["项目工作流升级或文档审阅"]
    assert plan["tool"]["status"] == "unchanged"
    after = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_plan_fingerprint_rejects_changed_scope_before_write(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    plan = unified_upgrade.build_plan(project=project)
    (project / "AGENTS.md").write_text((project / "AGENTS.md").read_text(encoding="utf-8") + "\n用户修改\n", encoding="utf-8")
    before = {path.relative_to(project).as_posix(): path.read_bytes() for path in project.rglob("*") if path.is_file()}

    assert unified_upgrade.build_plan(project=project)["plan_fingerprint"] != plan["plan_fingerprint"]

    after = {path.relative_to(project).as_posix(): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    assert after == before


def test_apply_cli_rejects_stale_plan_without_writing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path / "project")
    plan = unified_upgrade.build_plan(project=project)
    (project / "AGENTS.md").write_text((project / "AGENTS.md").read_text(encoding="utf-8") + "\n用户再次修改\n", encoding="utf-8")
    before = {path.relative_to(project).as_posix(): path.read_bytes() for path in project.rglob("*") if path.is_file()}

    exit_code = unified_upgrade.main([
        "apply", "--project", str(project), "--upgrade-project",
        "--plan-fingerprint", plan["plan_fingerprint"], "--json",
    ])

    assert exit_code == 4
    assert "计划指纹失效" in capsys.readouterr().err
    assert {path.relative_to(project).as_posix(): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before


def test_apply_project_keeps_existing_safe_upgrade_and_reports_review(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    item = project / ".agent-workflow/30-records/work-items/W-old"
    item.mkdir(parents=True)
    (item / "work-item.md").write_text(
        "# 旧任务\n\n- ID：`W-old`\n- 标题：旧任务\n- 类型：需求\n- 状态：in_progress\n- 父工作项：无\n",
        encoding="utf-8",
    )
    plan = unified_upgrade.build_plan(project=project)

    result = unified_upgrade.apply_plan(plan, project, None, None, False, True, False)

    assert result["results"]["project"]["applied"] is True
    assert (project / ".agent-workflow/WORKFLOW_VERSION").read_text(encoding="utf-8") == "6\n"
    assert task_context.read_state(item)["status"] == "in_progress"
    assert result["status"] == "pending"
    assert result["after"]["project"]["review_pending"] is True


def test_apply_requires_an_explicit_scope(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    assert unified_upgrade.main(["apply", "--project", str(project), "--json"]) == 4


def test_json_plan_has_stable_fingerprint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path / "project", version=5)
    exit_code = unified_upgrade.main(["plan", "--project", str(project), "--json"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["summary"]["plan_fingerprint"] == output["plan_fingerprint"]
    assert len(output["plan_fingerprint"]) == 64
