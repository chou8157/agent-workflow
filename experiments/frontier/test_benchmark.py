"""核验基准环境别名不会导致所有来源被误判。"""
from pathlib import Path

from experiments.frontier.benchmark import run_case, summarize


def test_benchmark_accepts_workspace_directory_alias(tmp_path):
    workspace = tmp_path / "actual"
    workspace.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(workspace, target_is_directory=True)
    rows, datasets = [], []
    run_case(alias, 1, "flat", 1, 1, rows, datasets)
    assert len(rows) == 4
    assert all(row["status"] == "pass" for row in rows)
    assert all(Path(row["result_artifact"]).exists() for row in rows)


def test_failed_samples_remain_in_denominator_but_not_timing_rank():
    shared = dict(nodes=1, shape="flat", facts_per_node=1, backend="file", strategy="central")
    result = summarize([dict(shared, status="fail", query_ms=0.1),
                        dict(shared, status="pass", query_ms=12)])[0]
    assert result["samples"] == 2
    assert result["passed"] == result["failed"] == 1
    assert result["query_ms"]["median"] == 12
