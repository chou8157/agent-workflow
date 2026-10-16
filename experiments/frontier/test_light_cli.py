"""最小入口的临时项目验收，不写真实项目。"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import date

import pytest

from experiments.frontier import light_cli, node_workflow as workflow


FIXTURES = Path(__file__).resolve().parent / "fixtures/p4/nodes"
SCRIPT = Path(__file__).resolve().parent / "light_cli.py"


def _projects(tmp_path):
    nodes = tmp_path / "nodes"
    shutil.copytree(FIXTURES, nodes)
    for project in nodes.iterdir():
        (project / workflow.IDENTITY).unlink()
    return nodes, tmp_path / "control/registry.sqlite"


def _run(command, project, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), command, "--project", str(project), *extra],
                          capture_output=True, text=True)


def _connect(nodes, registry):
    commands = (("root", ("--registry", str(registry))),
                ("middle", ("--parent", str(nodes / "root"))),
                ("leaf", ("--parent", str(nodes / "middle"))))
    for node, extra in commands:
        result = _run("connect", nodes / node, *extra)
        assert result.returncode == 0, result.stderr
    return commands


def _item(project):
    return next((project / workflow.ITEMS).glob("W-*"))


def _hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _record(project, activity_date="2026-10-13", summary="完成本地验证", identifier=None):
    item = _item(project)
    evidence = item / "progress/closeout-evidence.md"
    evidence.parent.mkdir(exist_ok=True)
    if not evidence.exists():
        evidence.write_text("# 验证结果\n三项检查通过。\n", encoding="utf-8")
    extra = ("--id", identifier) if identifier else ()
    return _run("record", project, "--item", item.name, "--date", activity_date,
                "--summary", summary, "--status", "completed", "--evidence",
                evidence.relative_to(project).as_posix(), "--line-start", "2", "--line-end", "2", *extra)


def test_connect_cli_builds_three_levels_and_retries_without_registry_changes(tmp_path):
    nodes, registry = _projects(tmp_path)
    commands = _connect(nodes, registry)
    store = workflow.registry_factory(registry, "sqlite")
    try:
        before = store.snapshot()
        before_files = _hashes(nodes)
        for node, extra in commands:
            retried = _run("connect", nodes / node, *extra)
            assert retried.returncode == 0, retried.stderr
            assert "unchanged" in retried.stdout
        assert store.snapshot() == before
        assert _hashes(nodes) == before_files
        assert before["edges"] == [
            {"source": "middle", "target": "leaf", "kind": "contains"},
            {"source": "root", "target": "middle", "kind": "contains"},
        ]
    finally:
        store.close()


def test_connect_refuses_configuration_replacement_and_missing_configured_database(tmp_path):
    nodes, registry = _projects(tmp_path)
    light_cli.connect(nodes / "root", registry)
    before = _hashes(nodes)
    with pytest.raises(ValueError, match="不同关系库"):
        light_cli.connect(nodes / "root", tmp_path / "other.sqlite")
    assert not (tmp_path / "other.sqlite").exists()
    assert _hashes(nodes) == before

    workflow.initialize_node(nodes / "middle", "middle")
    workflow.enable(nodes / "middle", tmp_path / "old.json", "file")
    before = _hashes(nodes)
    with pytest.raises(ValueError, match="非 SQLite"):
        light_cli.connect(nodes / "middle", registry)
    assert _hashes(nodes) == before

    registry.rename(tmp_path / "kept.sqlite")
    with pytest.raises(ValueError, match="拒绝创建空库替代"):
        light_cli.connect(nodes / "root", registry)
    assert not registry.exists()


def test_connect_refuses_cycle_before_mutating_node_configuration(tmp_path):
    nodes, registry = _projects(tmp_path)
    _connect(nodes, registry)
    before = _hashes(nodes)
    with pytest.raises(ValueError, match="成环"):
        light_cli.connect(nodes / "root", parent=nodes / "leaf")
    assert _hashes(nodes) == before


def test_record_cli_is_local_and_retry_survives_appended_evidence(tmp_path):
    nodes, registry = _projects(tmp_path)
    project = nodes / "leaf"
    first = _record(project)
    assert first.returncode == 0, first.stderr
    item = _item(project)
    evidence = item / "progress/closeout-evidence.md"
    evidence.write_text(evidence.read_text(encoding="utf-8") + "随后追加的新验证。\n", encoding="utf-8")
    before = _hashes(nodes)
    repeated = _record(project)
    assert repeated.returncode == 0, repeated.stderr
    assert "unchanged" in repeated.stdout
    assert _hashes(nodes) == before
    assert not registry.exists()
    assert not (project / workflow.IDENTITY).exists()
    state = json.loads((item / ".state.json").read_text(encoding="utf-8"))
    assert len(state["activity_records"]) == 1
    assert state["activity_records"][0]["evidence_refs"][0]["hash_scope"] == "lines"
    evidence.write_text("# 验证结果\n修改了被引用的结果。\n", encoding="utf-8")
    conflicting = _record(project)
    assert conflicting.returncode == 2
    assert "冲突" in conflicting.stderr or "不同内容" in conflicting.stderr
    assert len(json.loads((item / ".state.json").read_text(encoding="utf-8"))["activity_records"]) == 1


def test_weekly_report_cli_preserves_range_sources_gaps_and_read_only_contract(tmp_path):
    nodes, registry = _projects(tmp_path)
    _connect(nodes, registry)
    for node, activity_date, summary in (("middle", "2026-10-12", "上周活动"),
                                         ("leaf", "2026-10-13", "本周开始活动"),
                                         ("leaf", "2026-10-19", "本周结束活动"),
                                         ("leaf", "2026-10-20", "下周活动")):
        recorded = _record(nodes / node, activity_date, summary)
        assert recorded.returncode == 0, recorded.stderr
    before = _hashes(nodes)
    args = ("--source-root", str(nodes), "--start", "2026-10-13", "--end", "2026-10-19")
    report = _run("report", nodes / "root", *args)
    assert report.returncode == 0, report.stderr
    assert "本周开始活动" in report.stdout and "本周结束活动" in report.stdout
    assert "上周活动" not in report.stdout and "下周活动" not in report.stdout
    assert "unknown_date" in report.stdout and "不能判断该范围内是否有工作" in report.stdout
    assert "来源 SHA-256" in report.stdout and "closeout-evidence.md:2-2" in report.stdout
    assert "哈希范围：lines" in report.stdout and "包含起止日" in report.stdout
    assert _hashes(nodes) == before

    partial = _run("report", nodes / "root", *args, "--deny", "leaf")
    assert partial.returncode == 2
    assert "[leaf] 本次请求明确拒绝读取" in partial.stdout
    assert "本周开始活动" not in partial.stdout
    assert "节点读取状态：partial" in partial.stdout
    skipped = _run("report", nodes / "root", *args, "--max-depth", "1")
    assert skipped.returncode == 2
    assert "[leaf] depth_budget" in skipped.stdout
    assert _hashes(nodes) == before

    failed_output = _run("report", nodes / "root", *args, "--output", str(nodes / "report.md"))
    assert failed_output.returncode == 2
    assert "来源目录之外" in failed_output.stderr
    assert _hashes(nodes) == before

    store = workflow.registry_factory(registry, "sqlite")
    try:
        registry_before = store.snapshot()
        blocked_database = _run("report", nodes / "root", *args, "--output", str(registry))
        assert blocked_database.returncode == 2
        assert "不能覆盖关系库" in blocked_database.stderr
        assert store.snapshot() == registry_before
    finally:
        store.close()


def test_unreadable_node_is_reported_and_detached_node_can_record_locally(tmp_path):
    nodes, registry = _projects(tmp_path)
    _connect(nodes, registry)
    missing = _item(nodes / "middle") / ".state.json"
    missing.unlink()
    report = _run("report", nodes / "root", "--source-root", str(nodes),
                  "--start", "2026-10-13", "--end", "2026-10-19")
    assert report.returncode == 2
    assert "[middle]" in report.stdout and "缺失或损坏" in report.stdout
    detached = _run("leave", nodes / "leaf")
    assert detached.returncode == 0, detached.stderr
    assert not workflow.identity(nodes / "leaf")["network_enabled"]
    registry.rename(tmp_path / "offline.sqlite")
    recorded = _record(nodes / "leaf")
    assert recorded.returncode == 0, recorded.stderr


def test_record_rejects_out_of_scope_evidence(tmp_path):
    nodes, _ = _projects(tmp_path)
    project = nodes / "root"
    outside = project / "outside.md"
    outside.write_text("项目外层文档\n", encoding="utf-8")
    with pytest.raises(ValueError, match=".agent-workflow"):
        light_cli.record(project, _item(project).name, "2026-10-13", "结果", "completed", "outside.md", 1, 1)


def test_report_rejects_invalid_dates(tmp_path):
    nodes, registry = _projects(tmp_path)
    _connect(nodes, registry)
    invalid = _run("report", nodes / "root", "--source-root", str(nodes),
                   "--start", "2026-10-20", "--end", "2026-10-13")
    assert invalid.returncode == 2
    assert "活动日期范围无效" in invalid.stderr


def test_standalone_report_needs_no_identity_or_registry_and_is_read_only(tmp_path):
    nodes, registry = _projects(tmp_path)
    project = nodes / "leaf"
    assert _record(project).returncode == 0
    before = _hashes(nodes)
    report = _run("report", project, "--source-root", str(project), "--scope", "self",
                  "--start", "2026-10-13", "--end", "2026-10-19")
    assert report.returncode == 0, report.stderr
    assert "完成本地验证" in report.stdout
    assert "计划覆盖：1 个节点" in report.stdout
    assert _hashes(nodes) == before
    assert not registry.exists()
    assert not (project / workflow.IDENTITY).exists()


def test_standalone_report_survives_broken_network_and_never_reads_child(tmp_path):
    nodes, registry = _projects(tmp_path)
    _connect(nodes, registry)
    assert _record(nodes / "root", summary="根节点本地成果").returncode == 0
    assert _record(nodes / "leaf", summary="不应读取的子节点成果").returncode == 0
    registry.write_bytes(b"broken-network")
    before = _hashes(nodes)
    report = _run("report", nodes / "root", "--source-root", str(nodes), "--scope", "self",
                  "--start", "2026-10-13", "--end", "2026-10-19")
    assert report.returncode == 0, report.stderr
    assert "根节点本地成果" in report.stdout
    assert "不应读取的子节点成果" not in report.stdout
    assert _hashes(nodes) == before


@pytest.mark.parametrize("today,week,expected", [
    (date(2026, 10, 19), "this", ("2026-10-19", "2026-10-25")),
    (date(2026, 10, 18), "this", ("2026-10-12", "2026-10-18")),
    (date(2026, 1, 1), "last", ("2025-12-22", "2025-12-28")),
])
def test_week_range_has_explicit_calendar_boundaries(today, week, expected):
    assert light_cli.week_range(week, today) == expected


def test_save_report_returns_bounded_pointer_and_keeps_partial_report(tmp_path):
    nodes, registry = _projects(tmp_path)
    _connect(nodes, registry)
    assert _record(nodes / "root", summary="详细事实应留在报告文件").returncode == 0
    before = _hashes(nodes)
    result = _run("report", nodes / "root", "--source-root", str(nodes),
                  "--start", "2026-10-13", "--end", "2026-10-19", "--deny", "leaf", "--save")
    assert result.returncode == 2, result.stderr
    assert len(result.stdout.encode("utf-8")) < 1024
    assert "详细事实应留在报告文件" not in result.stdout
    report = Path(result.stdout.splitlines()[0].split("：", 1)[1])
    try:
        content = report.read_text(encoding="utf-8")
        assert "详细事实应留在报告文件" in content
        assert "[leaf] 本次请求明确拒绝读取" in content
        assert _hashes(nodes) == before
    finally:
        report.unlink()
        report.parent.rmdir()


def test_week_option_cannot_silently_override_explicit_dates(tmp_path):
    nodes, _ = _projects(tmp_path)
    before = _hashes(nodes)
    result = _run("report", nodes / "root", "--source-root", str(nodes), "--scope", "self",
                  "--week", "this", "--start", "2026-10-13", "--end", "2026-10-19")
    assert result.returncode == 2
    assert "不能与" in result.stderr
    assert _hashes(nodes) == before


def test_standalone_report_respects_registered_id_in_deny_list(tmp_path):
    nodes, registry = _projects(tmp_path)
    light_cli.connect(nodes / "root", registry, node_id="restricted-node")
    before = _hashes(nodes)
    result = _run("report", nodes / "root", "--source-root", str(nodes), "--scope", "self",
                  "--week", "this", "--deny", "restricted-node")
    assert result.returncode == 2
    assert "拒绝读取" in result.stderr
    assert not result.stdout
    assert _hashes(nodes) == before
