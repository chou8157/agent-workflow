"""未接入产品的隔离实验：关系原型不可用时，原始单节点 CLI 仍可独立运行。"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from experiments.frontier.file_store import FileRegistry
from experiments.frontier.sqlite_store import SQLiteRegistry


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "agent-workflow" / "scripts"


def _environment():
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def _cli(script, project, *arguments):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), str(project)] + list(arguments),
        cwd=str(project.parent), env=_environment(), capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, "{} {}\n{}\n{}".format(script, arguments, result.stdout, result.stderr)
    return result.stdout


def _hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_sqlite_package_import_works_in_fresh_process_without_creating_authority(tmp_path):
    authority = tmp_path / "unused.sqlite"
    result = subprocess.run(
        [sys.executable, "-c",
         "from experiments.frontier.sqlite_store import SQLiteRegistry; "
         "import sys; registry = SQLiteRegistry(sys.argv[1]); registry.close()",
         str(authority)],
        cwd=str(ROOT), env=_environment(), capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not authority.exists()


@pytest.mark.parametrize("registry_type,filename", [
    (FileRegistry, "registry.json"),
    (SQLiteRegistry, "registry.sqlite"),
], ids=["file", "sqlite"])
@pytest.mark.parametrize("fault", ["closed", "corrupted"])
def test_original_local_cli_is_independent_of_unavailable_registry(tmp_path, registry_type, filename, fault):
    local = tmp_path / "local-node"
    external = tmp_path / "external-node"
    for node_id, project in (("local", local), ("external", external)):
        _cli("scaffold_workflow.py", project)
        (project / "facts.json").write_text(json.dumps({
            "node_id": node_id, "view_id": "main",
            "facts": [{"record_id": "existing-fact", "revision": 1,
                       "occurred_at": "2026-10-10T09:00:00+08:00", "value": "原始记录"}],
        }, ensure_ascii=False) + "\n", encoding="utf-8")
    external_before = _hashes(external)

    # 同一个本地项目先在没有关系库时工作，再继续完成已有任务并创建新任务。
    _cli("task_context.py", local, "create", "W-existing", "--title", "既有本地任务")
    _cli("task_context.py", local, "set-status", "W-existing", "in_progress")
    assert json.loads(_cli("check_workflow.py", local, "--require-work-items", "--json"))["ok"]

    control = tmp_path / "network-control"
    authority = control / filename
    registry = registry_type(authority)
    registry.initialize(
        [{"id": "local", "locator": str(local / "facts.json")},
         {"id": "external", "locator": str(external / "facts.json")}],
        [{"source": "local", "target": "external", "kind": "contains"}],
    )
    assert registry.snapshot()["revision"] == 1
    registry.close()
    if fault == "corrupted":
        authority.write_bytes(b"broken relation authority\n")
        registry = registry_type(authority)
    with pytest.raises(ValueError):
        registry.snapshot()
    control_before = _hashes(control)

    _cli("task_context.py", local, "set-status", "W-existing", "completed")
    completed = json.loads(_cli("task_context.py", local, "show", "W-existing", "--json"))
    assert completed["status"] == "completed"
    _cli("task_context.py", local, "create", "W-offline", "--title", "关系不可用时的新任务")
    _cli("task_context.py", local, "set-status", "W-offline", "in_progress")
    created = json.loads(_cli("task_context.py", local, "show", "W-offline", "--json"))
    assert created["status"] == "in_progress"
    assert {item["id"] for item in json.loads(_cli("task_context.py", local, "list", "--json"))} == {"W-existing", "W-offline"}
    assert json.loads(_cli("check_workflow.py", local, "--require-work-items", "--json")) == {
        "ok": True, "project": str(local.resolve()), "issues": [],
    }

    assert _hashes(external) == external_before
    assert _hashes(control) == control_before
    with pytest.raises(ValueError):
        registry.snapshot()
    registry.close()
