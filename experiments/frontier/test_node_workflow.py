"""P4 原工作项副本上的自治、恢复和原文来源验收。"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from experiments.frontier import node_workflow as workflow


FIXTURES = Path(__file__).resolve().parent / "fixtures/p4"
WORK_ITEMS = {
    "root": "W-20260911-workflow-optimization",
    "middle": "W-20260715-workflow-upgrade",
    "leaf": "W-20260715-multi-work-items",
}
EXPECTED = {
    ("root", "W-20260911-workflow-optimization"),
    ("middle", "W-20260715-workflow-upgrade"),
    ("leaf", "W-20260715-multi-work-items"),
}
CLI_OBSERVATIONS = []


@pytest.fixture(scope="session", autouse=True)
def write_cli_observations():
    yield
    destination = os.environ.get("P4_CLI_EVIDENCE")
    if destination:
        Path(destination).write_text(json.dumps(CLI_OBSERVATIONS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cli(*arguments, expected_code=0):
    command = [sys.executable, str(Path(workflow.__file__).resolve())] + [str(arg) for arg in arguments]
    result = subprocess.run(command, capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=30)
    payload = json.loads(result.stdout.decode("utf-8"))
    CLI_OBSERVATIONS.append({"arguments": command[2:], "stdout_bytes": len(result.stdout),
                             "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                             "returncode": result.returncode, "stdout": payload})
    assert result.returncode == expected_code, result.stderr.decode("utf-8") + str(payload)
    assert not result.stderr
    if arguments[0] != "local":
        assert len(result.stdout) <= workflow.MAX_OUTPUT_BYTES
    return payload


def page_all(handle, source_root, kind="facts", budget=4096):
    cursor, records = 0, []
    while True:
        page = cli("page", "--handle", handle, "--source-root", source_root,
                   "--kind", kind, "--cursor", cursor, "--max-bytes", budget)
        assert len(workflow.encoded(page)) <= budget
        assert page["cursor"] == cursor
        records.extend(page["records"])
        if page["done"]:
            assert page["next_cursor"] is None
            assert len(records) == page["total"]
            return records
        assert page["next_cursor"] == cursor + len(page["records"])
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.fixture(params=["file", "sqlite", "log"])
def network(tmp_path, request):
    nodes = tmp_path / "nodes"
    shutil.copytree(str(FIXTURES / "nodes"), str(nodes))
    backend = request.param
    registry = tmp_path / ("control/registry." + backend)
    workflow.network_initialize(registry, backend)
    for node in ("root", "middle", "leaf"):
        project = nodes / node
        workflow.enable(project, registry, backend)
        workflow.join(project, {"root": None, "middle": "root", "leaf": "middle"}[node])
    workflow.join(nodes / "leaf", "root")
    return nodes, registry


def registry_class(registry):
    return workflow.BACKENDS[registry.suffix[1:]]


def corrupt_registry(registry):
    target = registry / "head.json" if registry.is_dir() else registry
    target.write_text("broken registry", encoding="utf-8")


def identities(result):
    found = {(f["origin_node_id"], f["work_item_id"]) for f in result["facts"]}
    assert len(found) == len(result["facts"])
    return found


@pytest.mark.parametrize("node", ["root", "middle", "leaf"])
@pytest.mark.parametrize("condition", ["disabled", "corrupted", "disconnected", "exited"])
def test_local_cli_reads_and_writes_each_role_without_network_dependency(network, node, condition):
    nodes, registry = network
    project = nodes / node
    if condition == "disabled":
        config = workflow.identity(project)
        config["network_enabled"] = False
        workflow.atomic_json(project / workflow.IDENTITY, config)
    elif condition == "corrupted":
        corrupt_registry(registry)
    elif condition == "disconnected":
        store = registry_class(registry)(registry)
        current = store.snapshot()
        store.apply(current["revision"], remove_edges=current["edges"])
        store.close()
    else:
        assert workflow.leave(project)["registry_cleanup"] == "complete"
    outside_before = {other: hashes(nodes / other) for other in WORK_ITEMS if other != node}
    control_before = hashes(registry.parent)
    metadata_before = (project / workflow.IDENTITY).read_bytes()

    for arguments in (["create", "W-p4-local", "--title", "P4 本地自治任务"],
                      ["set-status", "W-p4-local", "in_progress"],
                      ["set-status", "W-p4-local", "completed"]):
        result = workflow.local(project, arguments)
        assert result["returncode"] == 0, result
    shown = workflow.local(project, ["show", "W-p4-local", "--json"])
    assert shown["returncode"] == 0
    assert json.loads(shown["stdout"])["status"] == "completed"
    reread = workflow.read_node(project)
    assert reread["status"] == "full"
    assert (node, "W-p4-local") in identities(reread)
    assert control_before == hashes(registry.parent)
    assert outside_before == {other: hashes(nodes / other) for other in WORK_ITEMS if other != node}
    assert metadata_before == (project / workflow.IDENTITY).read_bytes()


def test_fresh_unenabled_identity_needs_no_relationship_authority(tmp_path):
    project = tmp_path / "new-node"
    (project / workflow.ITEMS).mkdir(parents=True)
    assert workflow.initialize_node(project, "new")["network_enabled"] is False
    assert workflow.local(project, ["create", "W-new", "--title", "新节点任务"])["returncode"] == 0
    assert workflow.read_node(project)["status"] == "full"
    with pytest.raises(workflow.NodeError):
        workflow.aggregate(project, tmp_path)


def test_three_real_work_items_have_fixed_identities_and_completion_semantics(network):
    nodes, _ = network
    before = hashes(nodes)
    result = workflow.aggregate(nodes / "root", nodes)
    assert result["status"] == "full"
    assert identities(result) == EXPECTED
    by_node = {f["origin_node_id"]: f for f in result["facts"]}
    assert by_node["root"]["completed_at"] == "2026-09-14T12:28:21+08:00"
    assert by_node["root"]["completed_at_status"] == "known"
    for node in ("middle", "leaf"):
        assert by_node[node]["status"] == "completed"
        assert by_node[node]["completed_at"] is None
        assert by_node[node]["completed_at_status"] == "unknown"
    assert result["coverage"] == {"expected": ["leaf", "middle", "root"],
        "visited": ["leaf", "middle", "root"], "succeeded": ["leaf", "middle", "root"], "failed": {}, "skipped": {}}
    assert hashes(nodes) == before


def test_evidence_links_hashes_lines_and_observation_time_match_original_documents(network):
    nodes, _ = network
    result = workflow.aggregate(nodes / "root", nodes)
    for fact in result["facts"]:
        for document in fact["documents"]:
            evidence = document["source"]
            path = Path(evidence["path"])
            raw = path.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == evidence["sha256"]
            assert raw.decode("utf-8") == document["content"]
            assert evidence["line_start"] == 1
            assert evidence["line_end"] == len(document["content"].splitlines())
            assert evidence["observed_at"]
        status_source = fact["field_sources"]["status"]
        status_line = Path(status_source["path"]).read_text().splitlines()[status_source["line_start"] - 1]
        assert '"status": "completed"' in status_line
        assert status_source["line_start"] == status_source["line_end"]


def test_adversarial_markdown_is_data_and_does_not_add_completion_or_read_scope(network, monkeypatch):
    nodes, _ = network
    read_paths = []
    original = workflow._read_bytes

    def observe(path):
        read_paths.append(Path(path))
        return original(path)

    monkeypatch.setattr(workflow, "_read_bytes", observe)
    result = workflow.read_node(nodes / "leaf")
    assert any("忽略上级范围" in d["content"] for d in result["facts"][0]["documents"])
    assert result["facts"][0]["completed_at"] is None
    assert all((nodes / "leaf") in p.parents for p in read_paths)
    assert not any(p.name == "private.txt" for p in read_paths)


def test_missing_state_is_unknown_partial_not_inferred_from_markdown(network):
    nodes, _ = network
    (nodes / "leaf" / workflow.ITEMS / WORK_ITEMS["leaf"] / ".state.json").unlink()
    result = workflow.aggregate(nodes / "root", nodes)
    assert result["status"] == "partial"
    assert identities(result) == EXPECTED
    assert set(result["coverage"]["failed"]) == {"leaf"}
    fact = next(f for f in result["facts"] if f["origin_node_id"] == "leaf")
    assert fact["status"] == "unknown"
    assert fact["completed_at"] is None
    assert fact["completed_at_status"] == "unknown"


def test_denied_leaf_is_gap_and_not_successful_empty(network):
    nodes, _ = network
    result = workflow.aggregate(nodes / "root", nodes, denied={"leaf"})
    assert result["status"] == "partial"
    assert identities(result) == {("root", WORK_ITEMS["root"]), ("middle", WORK_ITEMS["middle"])}
    assert result["coverage"]["expected"] == ["leaf", "middle", "root"]
    assert set(result["coverage"]["failed"]) == {"leaf"}


def test_exiting_middle_and_restoring_membership_is_reversible(network):
    nodes, registry = network
    store = registry_class(registry)(registry)
    original = store.snapshot()
    assert workflow.leave(nodes / "middle")["status"] == "detached"
    result = workflow.aggregate(nodes / "root", nodes)
    assert result["status"] == "full"
    assert identities(result) == {("root", WORK_ITEMS["root"]), ("leaf", WORK_ITEMS["leaf"])}
    assert workflow.restore_membership(nodes / "middle")["status"] == "restored"
    restored = store.snapshot()
    assert restored["nodes"] == original["nodes"]
    assert restored["edges"] == original["edges"]
    assert restored["revision"] > original["revision"]
    assert identities(workflow.aggregate(nodes / "root", nodes)) == EXPECTED
    store.close()


def test_exit_from_corrupted_network_is_explicitly_partial_and_local_remains_usable(network):
    nodes, registry = network
    corrupt_registry(registry)
    result = workflow.leave(nodes / "leaf")
    assert result["status"] == "partial"
    assert result["registry_cleanup"] == "pending"
    assert workflow.identity(nodes / "leaf")["network_enabled"] is False
    assert workflow.local(nodes / "leaf", ["list", "--json"])["returncode"] == 0


def test_relocation_keeps_identity_and_fact_bytes_and_can_move_back(network):
    nodes, _ = network
    before = hashes(nodes / "leaf")
    moved = nodes / "leaf-moved"
    assert workflow.relocate(nodes / "leaf", moved, nodes)["node_id"] == "leaf"
    assert workflow.identity(moved)["node_id"] == "leaf"
    assert hashes(moved) == before
    result = workflow.aggregate(nodes / "root", nodes)
    assert identities(result) == EXPECTED
    leaf = next(f for f in result["facts"] if f["origin_node_id"] == "leaf")
    assert all(str(moved) in item["path"] for item in leaf["sources"])
    workflow.relocate(moved, nodes / "leaf", nodes)
    assert hashes(nodes / "leaf") == before


def test_relocation_before_commit_failure_restores_original_location(network, monkeypatch):
    nodes, registry = network

    def fail(*args, **kwargs):
        raise ValueError("injected precommit failure")

    monkeypatch.setattr(registry_class(registry), "apply", fail)
    with pytest.raises(ValueError):
        workflow.relocate(nodes / "leaf", nodes / "leaf-moved", nodes)
    assert (nodes / "leaf").is_dir()
    assert not (nodes / "leaf-moved").exists()
    assert identities(workflow.aggregate(nodes / "root", nodes)) == EXPECTED


def test_relocation_rechecks_commit_instead_of_rolling_back_success(network, monkeypatch):
    nodes, registry = network
    original_apply = registry_class(registry).apply

    def committed_then_error(self, *args, **kwargs):
        original_apply(self, *args, **kwargs)
        raise OSError("injected uncertain acknowledgement")

    monkeypatch.setattr(registry_class(registry), "apply", committed_then_error)
    result = workflow.relocate(nodes / "leaf", nodes / "leaf-moved", nodes)
    assert result["status"] == "moved_commit_rechecked"
    assert not (nodes / "leaf").exists()
    assert identities(workflow.aggregate(nodes / "root", nodes)) == EXPECTED


def test_uncertain_relocation_reports_location_and_supports_explicit_reconciliation(network, monkeypatch):
    nodes, registry = network
    original_snapshot = registry_class(registry).snapshot
    calls = []

    def snapshot_then_fail(self):
        calls.append(True)
        if len(calls) > 1:
            raise OSError("injected registry unavailable")
        return original_snapshot(self)

    def fail_apply(*args, **kwargs):
        raise OSError("injected commit unavailable")

    with monkeypatch.context() as context:
        context.setattr(registry_class(registry), "snapshot", snapshot_then_fail)
        context.setattr(registry_class(registry), "apply", fail_apply)
        result = workflow.relocate(nodes / "leaf", nodes / "leaf-moved", nodes)
    assert result["status"] == "partial"
    assert result["registry_reconciliation_required"] is True
    assert result["project"] == str(nodes / "leaf-moved")
    assert workflow.local(nodes / "leaf-moved", ["list", "--json"])["returncode"] == 0
    assert workflow.aggregate(nodes / "root", nodes)["status"] == "partial"
    assert workflow.reconcile_location(nodes / "leaf-moved", nodes)["status"] == "reconciled"
    assert identities(workflow.aggregate(nodes / "root", nodes)) == EXPECTED


def test_reconciliation_rejects_competing_existing_identity_copy(network):
    nodes, _ = network
    shutil.copytree(str(nodes / "leaf"), str(nodes / "leaf-copy"))
    with pytest.raises(workflow.NodeError):
        workflow.reconcile_location(nodes / "leaf-copy", nodes)
    assert identities(workflow.aggregate(nodes / "root", nodes)) == EXPECTED


def test_backup_is_not_an_active_authority_and_restore_verifies_every_file(network, tmp_path):
    nodes, _ = network
    project, backup = nodes / "leaf", tmp_path / "backup-leaf"
    before = hashes(project)
    workflow.backup_node(project, backup)
    with pytest.raises(workflow.NodeError):
        workflow.read_node(backup)
    with pytest.raises(workflow.NodeError):
        workflow.local(backup, ["create", "W-backup", "--title", "不得写入备份"])
    with pytest.raises(workflow.NodeError):
        workflow.join(backup)
    with pytest.raises(workflow.NodeError):
        workflow.restore_node(backup, project)
    project.rename(tmp_path / "retired-leaf")
    assert workflow.restore_node(backup, project)["node_id"] == "leaf"
    assert hashes(project) == before
    assert identities(workflow.aggregate(nodes / "root", nodes)) == EXPECTED


@pytest.mark.parametrize("tampering", ["extra", "content", "symlink"])
def test_backup_tampering_is_rejected(network, tmp_path, tampering):
    nodes, _ = network
    project, backup = nodes / "leaf", tmp_path / "backup-leaf"
    workflow.backup_node(project, backup)
    if tampering == "extra":
        (backup / "unexpected.txt").write_text("not in manifest")
    else:
        state = backup / workflow.ITEMS / WORK_ITEMS["leaf"] / ".state.json"
        if tampering == "content":
            state.write_text("{}")
        else:
            external = tmp_path / "external-state.json"
            external.write_text(state.read_text())
            state.unlink()
            state.symlink_to(external)
    project.rename(tmp_path / "retired-leaf")
    with pytest.raises(workflow.NodeError):
        workflow.restore_node(backup, project)
    assert not project.exists()


def test_document_symlink_escape_is_a_coverage_gap(network, tmp_path):
    nodes, _ = network
    source = nodes / "leaf" / workflow.ITEMS / WORK_ITEMS["leaf"] / "current-status.md"
    external = tmp_path / "secret.txt"
    external.write_text("external sentinel")
    source.unlink()
    source.symlink_to(external)
    result = workflow.aggregate(nodes / "root", nodes)
    assert result["status"] == "partial"
    assert set(result["coverage"]["failed"]) == {"leaf"}
    assert "external sentinel" not in json.dumps(result)


def test_local_write_rejects_workflow_symlink_before_invoking_stable_cli(network, tmp_path):
    nodes, _ = network
    external = tmp_path / "external"
    external.mkdir()
    (nodes / "leaf" / workflow.ITEMS / "W-escape").symlink_to(external, target_is_directory=True)
    with pytest.raises(workflow.NodeError):
        workflow.local(nodes / "leaf", ["create", "W-safe", "--title", "safe"])
    assert list(external.iterdir()) == []


def test_public_cli_reports_read_partial_and_unavailable_network(network, capsys):
    nodes, registry = network
    assert workflow.main(["read", "--project", str(nodes / "leaf")]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["fact_count"] == 1
    assert workflow.read_page(manifest["handle"], nodes / "leaf")["records"][0]["completed_at_status"] == "unknown"
    arguments = ["aggregate", "--project", str(nodes / "root"), "--source-root", str(nodes)]
    assert workflow.main(arguments + ["--deny", "leaf"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "partial"
    assert result["coverage"]["failed"] == 1
    assert workflow.read_page(result["handle"], nodes, "gaps")["records"][0]["origin_node_id"] == "leaf"
    corrupt_registry(registry)
    assert workflow.main(arguments) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


@pytest.mark.parametrize("config", [None, "broken", "[]", '{"backend":"not-supported"}'])
def test_original_local_cli_ignores_missing_or_invalid_optional_identity(tmp_path, config, monkeypatch):
    project = tmp_path / "plain-project"
    (project / workflow.ITEMS).mkdir(parents=True)
    if config is not None:
        (project / workflow.IDENTITY).write_text(config, encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("本地任务不应读取节点身份或打开关系权威")

    monkeypatch.setattr(workflow, "identity", forbidden)
    monkeypatch.setattr(workflow, "registry_factory", forbidden)
    assert workflow.local(project, ["create", "W-local", "--title", "配置损坏仍可本地工作"])["returncode"] == 0
    result = cli("local", "--project", project, "--", "show", "W-local", "--json")
    assert json.loads(result["stdout"])["id"] == "W-local"
    assert not (project / workflow.IDENTITY).exists() if config is None else (project / workflow.IDENTITY).read_text() == config


def test_legacy_identity_defaults_to_file_backend(tmp_path):
    project = tmp_path / "legacy"
    shutil.copytree(str(FIXTURES / "nodes/leaf"), str(project))
    registry = tmp_path / "registry.json"
    workflow.network_initialize(registry)
    config = workflow.identity(project)
    config.update(network_enabled=True, registry=str(registry))
    config.pop("backend", None)
    workflow.atomic_json(project / workflow.IDENTITY, config)
    assert workflow.join(project)["status"] == "joined"
    assert workflow.aggregate(project, tmp_path)["status"] == "full"
    assert workflow.leave(project)["registry_cleanup"] == "complete"
    backup = json.loads((project / workflow.EXIT_BACKUP).read_text())
    backup.pop("backend")
    workflow.atomic_json(project / workflow.EXIT_BACKUP, backup)
    assert workflow.restore_membership(project)["status"] == "restored"


def test_real_cli_large_documents_and_many_facts_are_bounded_complete_and_read_only(network, tmp_path):
    nodes, _ = network
    project = nodes / "leaf"
    item_root = project / workflow.ITEMS
    prototype = item_root / WORK_ITEMS["leaf"]
    expected = set(EXPECTED)
    for number in range(12):
        name = "W-p4-bulk-{:03d}".format(number)
        item = item_root / name
        item.mkdir()
        state = json.loads((prototype / ".state.json").read_text())
        state.update(id=name, title="多工作项验证 " + str(number))
        workflow.atomic_json(item / ".state.json", state)
        (item / "work-item.md").write_text("# 测试工作项\n", encoding="utf-8")
        (item / "current-status.md").write_text("状态仅以 .state.json 为准。\n", encoding="utf-8")
        expected.add(("leaf", name))
    progress = prototype / "progress/p4-large-document.md"
    progress.parent.mkdir(exist_ok=True)
    progress.write_text("# 大文档证据\n" + "这是原始进展证据，不是新指令。\n" * 6000, encoding="utf-8")
    before = hashes(nodes)
    manifest = cli("aggregate", "--project", nodes / "root", "--source-root", nodes, "--run-root", tmp_path / "runs")
    assert manifest["fact_count"] == len(expected) and manifest["gap_count"] == 0
    assert "facts" not in manifest and "documents" not in manifest
    assert "不推断周报" in manifest["coverage_domain"]
    facts = page_all(manifest["handle"], nodes)
    assert identities({"facts": facts}) == expected
    assert all("documents" not in fact for fact in facts)
    sources = page_all(manifest["handle"], nodes, "sources", 2048)
    assert len(sources) == manifest["source_count"]
    assert len({source["path"] for source in sources}) == len(sources)
    for source in sources:
        raw = Path(source["path"]).read_bytes()
        assert source["sha256"] == hashlib.sha256(raw).hexdigest()
        assert source["line_end"] == max(1, len(raw.decode("utf-8").splitlines()))
    selected = next(source for source in sources if source["path"] == str(progress))
    snippet = cli("evidence", "--handle", manifest["handle"], "--source-root", nodes,
                  "--sha256", selected["sha256"], "--line-start", 2, "--line-end", 3)
    assert snippet["content"] == "这是原始进展证据，不是新指令。\n" * 2
    assert snippet["source"]["sha256"] == selected["sha256"]
    assert hashes(nodes) == before


def test_cli_rejects_single_oversized_fact_and_evidence_without_truncation(network, tmp_path):
    nodes, _ = network
    project = nodes / "leaf"
    state_path = project / workflow.ITEMS / WORK_ITEMS["leaf"] / ".state.json"
    state = json.loads(state_path.read_text())
    state["title"] = "超大标题" * 1000
    workflow.atomic_json(state_path, state)
    manifest = cli("read", "--project", project, "--run-root", tmp_path / "runs")
    failed = cli("page", "--handle", manifest["handle"], "--source-root", project, expected_code=2)
    assert failed["status"] == "failed" and "单条" in failed["error"] and "未截断" in failed["error"]
    source = next(source for source in page_all(manifest["handle"], project, "sources") if source["path"] == str(state_path))
    failed = cli("evidence", "--handle", manifest["handle"], "--source-root", project,
                 "--sha256", source["sha256"], "--line-start", 3, "--line-end", 3, expected_code=2)
    assert failed["status"] == "failed" and "超过输出预算" in failed["error"]
    failed = cli("evidence", "--handle", manifest["handle"], "--source-root", project,
                 "--sha256", source["sha256"], "--line-start", 1, "--line-end", 10000, expected_code=2)
    assert "行号越界" in failed["error"]


@pytest.mark.parametrize("mutation", ["content", "new_item", "new_progress", "deleted", "identity", "registry"])
def test_cli_refuses_stale_runs_after_source_inventory_or_relationship_change(network, tmp_path, mutation):
    nodes, registry = network
    manifest = cli("aggregate", "--project", nodes / "root", "--source-root", nodes, "--run-root", tmp_path / "runs")
    item = nodes / "leaf" / workflow.ITEMS / WORK_ITEMS["leaf"]
    if mutation == "content":
        (item / "work-item.md").write_text("已变更", encoding="utf-8")
    elif mutation == "new_item":
        (nodes / "leaf" / workflow.ITEMS / "W-new-after-run").mkdir()
    elif mutation == "new_progress":
        (item / "new-progress.md").write_text("新的原文", encoding="utf-8")
    elif mutation == "deleted":
        (item / ".state.json").unlink()
    elif mutation == "identity":
        (nodes / "leaf" / workflow.IDENTITY).write_text("bad", encoding="utf-8")
    else:
        store = registry_class(registry)(registry)
        snapshot = store.snapshot()
        store.apply(snapshot["revision"])
        store.close()
    failed = cli("page", "--handle", manifest["handle"], "--source-root", nodes, expected_code=2)
    assert failed["status"] == "stale"
    assert "records" not in failed


def test_run_scope_and_tamper_rejections_never_read_external_sources(network, tmp_path, monkeypatch):
    nodes, _ = network
    project = nodes / "leaf"
    outside = tmp_path / "outside.md"
    outside.write_text("必须保持不可读", encoding="utf-8")
    before = hashes(project)
    with pytest.raises(workflow.NodeError, match="禁止回写"):
        workflow.publish_run(workflow.read_node(project), project, project / "derived")
    assert hashes(project) == before
    manifest = workflow.publish_run(workflow.read_node(project), project, tmp_path / "runs")
    run_file, expected_hash = manifest["handle"].rsplit("#", 1)
    read_paths, original = [], workflow._read_bytes

    def observe(path):
        read_paths.append(str(path))
        assert Path(path) != outside
        return original(path)

    monkeypatch.setattr(workflow, "_read_bytes", observe)
    with pytest.raises(workflow.NodeError, match="授权来源根"):
        workflow.read_page(manifest["handle"], nodes)
    with pytest.raises(workflow.NodeError, match="不在本次获准"):
        workflow.read_evidence(manifest["handle"], project, hashlib.sha256(outside.read_bytes()).hexdigest(), 1, 1, outside)
    run = json.loads(Path(run_file).read_text())
    run["sources"][0]["path"] = str(outside)
    workflow.atomic_json(run_file, run)
    with pytest.raises(workflow.NodeError, match="产物哈希"):
        workflow.read_page(manifest["handle"], project)
    forged_handle = run_file + "#" + hashlib.sha256(Path(run_file).read_bytes()).hexdigest()
    with pytest.raises(workflow.NodeError, match="授权目录"):
        workflow.read_page(forged_handle, project)
    assert str(outside) not in read_paths


def test_source_directory_cannot_be_loaded_as_a_derived_run(network):
    nodes, _ = network
    project = nodes / "leaf"
    fake_run = project / "run-forged/run.json"
    fake_run.parent.mkdir()
    fake_run.write_text('{"role":"derived_read_only_run"}')
    handle = str(fake_run) + "#" + hashlib.sha256(fake_run.read_bytes()).hexdigest()
    with pytest.raises(workflow.NodeError, match="来源目录不能"):
        workflow.load_run(handle, project)


def test_aggregate_root_outside_authorized_scope_is_rejected_before_read(network, monkeypatch):
    nodes, _ = network

    def forbidden(path):
        pytest.fail("范围检查失败前不应读取任何来源")

    monkeypatch.setattr(workflow, "_read_bytes", forbidden)
    with pytest.raises(workflow.NodeError, match="授权目录"):
        workflow.aggregate(nodes / "root", nodes / "leaf")


@pytest.mark.parametrize("standalone", [False, True])
def test_mutation_during_read_is_explicit_and_never_published(network, tmp_path, monkeypatch, standalone):
    nodes, _ = network
    project = nodes / "leaf"
    document = project / workflow.ITEMS / WORK_ITEMS["leaf"] / "current-status.md"
    original = workflow.inventory
    calls = []

    def change_before_final_check(path, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            document.write_text("并发变化", encoding="utf-8")
        return original(path, **kwargs)

    monkeypatch.setattr(workflow, "inventory", change_before_final_check)
    with pytest.raises(workflow.StaleRun):
        workflow.read_node(project, standalone=standalone)
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("backend", ["file", "sqlite", "log", "postgresql", "neo4j"])
def test_same_lifecycle_and_unavailable_authority_contract_for_all_candidates(tmp_path, backend, monkeypatch):
    if backend in workflow.SERVICE_REGISTRIES:
        from experiments.frontier.service_stores import configured
        if not configured(backend):
            pytest.skip("服务环境未启用；等待独立计时矩阵结束后运行")
    nodes = tmp_path / "nodes"
    shutil.copytree(str(FIXTURES / "nodes"), str(nodes))
    registry = "p2_p4_" + uuid.uuid4().hex if backend in workflow.SERVICE_REGISTRIES else tmp_path / ("registry." + backend)
    workflow.network_initialize(registry, backend)
    try:
        for node, parent in (("root", None), ("middle", "root"), ("leaf", "middle")):
            workflow.enable(nodes / node, registry, backend)
            workflow.join(nodes / node, parent)
        assert identities(workflow.aggregate(nodes / "root", nodes)) == EXPECTED
        assert workflow.leave(nodes / "middle")["registry_cleanup"] == "complete"
        assert workflow.restore_membership(nodes / "middle")["status"] == "restored"
        moved = nodes / "leaf-moved"
        workflow.relocate(nodes / "leaf", moved, nodes)
        assert identities(workflow.aggregate(nodes / "root", nodes)) == EXPECTED
        workflow.relocate(moved, nodes / "leaf", nodes)
        snapshot = workflow.registry_factory(registry, backend)
        before = snapshot.snapshot()
        snapshot.close()
        others_before = hashes(nodes / "middle"), hashes(nodes / "leaf")
        config = workflow.identity(nodes / "root")
        valid_registry = config["registry"]
        config["registry"] = "p2_absent_" + uuid.uuid4().hex if backend in workflow.SERVICE_REGISTRIES else str(tmp_path / "absent")
        workflow.atomic_json(nodes / "root" / workflow.IDENTITY, config)
        result = cli("local", "--project", nodes / "root", "--", "create", "W-p4-all", "--title", "五候选同口径自治")
        assert result["returncode"] == 0
        assert cli("aggregate", "--project", nodes / "root", "--source-root", nodes, expected_code=2)["status"] == "failed"
        assert workflow.leave(nodes / "root")["registry_cleanup"] == "pending"
        workflow.enable(nodes / "root", valid_registry, backend)
        assert (hashes(nodes / "middle"), hashes(nodes / "leaf")) == others_before
        store = workflow.registry_factory(registry, backend)
        assert store.snapshot() == before
        store.close()
    finally:
        if backend in workflow.SERVICE_REGISTRIES:
            cleanup = workflow.registry_factory(registry, backend)
            cleanup.delete_test_registry()
            cleanup.close()
