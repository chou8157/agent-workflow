"""模型入口的范围、深度、超时和响应预算回归。"""

import shutil
from pathlib import Path

import pytest

from experiments.frontier import bounded_node_query
from experiments.frontier import node_workflow


FIXTURES = Path(__file__).resolve().parent / "fixtures/p4/nodes"


@pytest.fixture
def network(tmp_path):
    nodes = tmp_path / "nodes"
    shutil.copytree(str(FIXTURES), str(nodes))
    registry = tmp_path / "control/registry.json"
    node_workflow.network_initialize(registry, "file")
    for node, parent in (("root", None), ("middle", "root"), ("leaf", "middle")):
        project = nodes / node
        node_workflow.enable(project, registry, "file")
        node_workflow.join(project, parent)
    return nodes, registry


def test_query_self_is_bounded_and_does_not_write_project(network, tmp_path):
    nodes, _ = network
    before = (nodes / "root/.agent-workflow/30-records/work-items/W-20260911-workflow-optimization/.state.json").read_bytes()
    result = bounded_node_query.query(nodes / "root", nodes, scope="self", max_nodes=1,
                                      max_depth=0, max_bytes=4096,
                                      run_root=tmp_path / "runs")
    assert result["status"] == "full"
    assert result["query"]["scope"] == "self"
    assert result["fact_count"] == 1
    assert before == (nodes / "root/.agent-workflow/30-records/work-items/W-20260911-workflow-optimization/.state.json").read_bytes()


def test_query_node_and_depth_budget_are_explicit(network, tmp_path):
    nodes, _ = network
    result = bounded_node_query.query(nodes / "root", nodes, max_nodes=1, max_depth=0,
                                      max_bytes=4096, run_root=tmp_path / "runs")
    assert result["status"] == "partial"
    assert result["query"]["max_nodes"] == 1
    assert result["coverage"]["skipped"] >= 1


@pytest.mark.parametrize("kwargs", [
    {"max_bytes": 255}, {"max_nodes": 0}, {"max_depth": -1}, {"timeout_seconds": 0},
])
def test_query_rejects_invalid_budget(network, tmp_path, kwargs):
    nodes, _ = network
    with pytest.raises((ValueError, node_workflow.NodeError)):
        bounded_node_query.query(nodes / "root", nodes, run_root=tmp_path / "runs", **kwargs)
