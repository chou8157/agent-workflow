"""第一阶段只读报告入口验证。"""

import hashlib
import shutil
from pathlib import Path
import subprocess
import sys

from experiments.frontier import node_workflow as workflow


FIXTURES = Path(__file__).resolve().parent / "fixtures/p4"
SCRIPT = Path(__file__).resolve().parent / "light_report.py"


def _copy_network(tmp_path):
    nodes = tmp_path / "nodes"
    shutil.copytree(FIXTURES / "nodes", nodes)
    registry = tmp_path / "control/registry.sqlite"
    workflow.network_initialize(registry, "sqlite")
    parents = {"root": None, "middle": "root", "leaf": "middle"}
    for node_id, parent in parents.items():
        project = nodes / node_id
        workflow.enable(project, registry, "sqlite")
        workflow.join(project, parent)
    return nodes


def _hashes(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def _run(nodes, output, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project", str(nodes / "root"),
         "--source-root", str(nodes), "--output", str(output), *extra],
        capture_output=True, text=True,
    )


def test_report_cli_writes_derived_markdown_without_mutating_nodes(tmp_path):
    nodes = _copy_network(tmp_path)
    before = _hashes(nodes)
    output = tmp_path / "derived/summary.md"

    result = _run(nodes, output)

    assert result.returncode == 0, result.stderr
    assert output.exists()
    report = output.read_text(encoding="utf-8")
    assert "# 多项目工作摘要" in report
    assert all("[{}]".format(node_id) in report for node_id in ("root", "middle", "leaf"))
    assert _hashes(nodes) == before


def test_report_cli_keeps_partial_status_visible_and_rejects_source_output(tmp_path):
    nodes = _copy_network(tmp_path)
    output = tmp_path / "derived/partial.md"

    result = _run(nodes, output, "--deny", "leaf")

    assert result.returncode == 2
    report = output.read_text(encoding="utf-8")
    assert "聚合状态：partial" in report
    assert "[leaf] 本次请求明确拒绝读取" in report

    failed = subprocess.run(
        [sys.executable, str(SCRIPT), "--project", str(nodes / "root"),
         "--source-root", str(nodes), "--output", str(nodes / "blocked.md")],
        capture_output=True, text=True,
    )
    assert failed.returncode == 2
    assert "授权来源目录之外" in failed.stderr
    assert not (nodes / "blocked.md").exists()


def test_report_cli_date_window_preserves_failed_skipped_and_unknown_date(tmp_path):
    nodes = _copy_network(tmp_path)
    output = tmp_path / "derived/weekly.md"
    before = _hashes(nodes)
    result = _run(nodes, output, "--start", "2026-10-13", "--end", "2026-10-19", "--deny", "middle", "--max-depth", "1")
    assert result.returncode == 2, result.stderr
    report = output.read_text(encoding="utf-8")
    assert "包含起止日" in report
    assert "[middle] 本次请求明确拒绝读取" in report
    assert "[leaf] depth_budget" in report
    assert "unknown_date" in report and "不能判断该范围内是否有工作" in report
    assert _hashes(nodes) == before


def test_report_cli_requires_both_dates(tmp_path):
    nodes = _copy_network(tmp_path)
    output = tmp_path / "derived/missing-date.md"
    result = _run(nodes, output, "--start", "2026-10-13")
    assert result.returncode == 2
    assert "同时提供" in result.stderr
    assert not output.exists()
