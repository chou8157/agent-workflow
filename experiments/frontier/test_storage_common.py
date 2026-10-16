"""跨后端的版本类型约束，防止 JSON 布尔值冒充 revision=1。"""
import pytest

from experiments.frontier.storage_common import mutated, validate


def test_boolean_snapshot_revision_is_rejected():
    with pytest.raises(ValueError, match="关系版本无效"):
        validate({"revision": True, "nodes": [], "edges": []})


def test_boolean_expected_revision_cannot_bypass_cas():
    with pytest.raises(ValueError, match="预期关系版本无效"):
        mutated({"revision": 1, "nodes": [], "edges": []}, True)
