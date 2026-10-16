"""P2 真服务契约测试；未配置隔离实例时明确 skip，不用模拟数据库顶替。"""

import multiprocessing
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from experiments.frontier.service_stores import REGISTRIES, configured
from experiments.frontier.storage_common import RevisionConflict, validate


NODES = [{"id": "b", "locator": "b.json"}, {"id": "a", "locator": "a.json"}]
EDGE = {"source": "a", "target": "b", "kind": "contains"}


@pytest.fixture(params=["postgresql", "neo4j"])
def service(request):
    backend = request.param
    if not configured(backend):
        pytest.skip(backend + " 专用环境未配置，not_run/environment")
    cls = REGISTRIES[backend]
    instances = []

    def create(namespace=None):
        instance = cls(namespace or "p2_test_" + uuid.uuid4().hex)
        instances.append(instance)
        return instance

    yield backend, create
    namespaces = {instance.namespace for instance in instances}
    for instance in instances:
        instance.close()
    for namespace in namespaces:
        cleanup = cls(namespace)
        try:
            cleanup.delete_test_registry()
        except FileNotFoundError:
            pass
        finally:
            cleanup.close()


def _reverse_competitor(backend, namespace, edge, ready, start, results):
    registry = REGISTRIES[backend](namespace)
    try:
        revision = registry.snapshot()["revision"]
        ready.put("ready")
        if not start.wait(20):
            raise TimeoutError("未收到并发启动信号")
        try:
            results.put(("committed", registry.apply(revision, add_edges=[edge])))
        except RevisionConflict:
            current = registry.snapshot()
            try:
                registry.apply(current["revision"], add_edges=[edge])
            except ValueError:
                results.put(("conflict_and_cycle_rejected", current["revision"]))
            else:
                results.put(("incorrect_cycle_commit", 0))
    except BaseException as error:
        results.put(("error", type(error).__name__ + ": " + str(error)))
    finally:
        registry.close()


def _uncommitted_writer(backend, namespace, ready, release):
    registry = REGISTRIES[backend](namespace)

    def pause(transaction):
        ready.set()
        release.wait(30)

    registry._before_commit = pause
    registry.apply(1, upsert_nodes=[{"id": "a", "locator": "uncommitted.json"}])


def test_initialize_reopen_and_refuse_overwrite(service):
    backend, create = service
    registry = create()
    initialized = registry.initialize(NODES, [EDGE])
    assert initialized["revision"] == 1
    assert registry.snapshot() == {"revision": 1, "nodes": sorted(NODES, key=lambda n: n["id"]), "edges": [EDGE]}
    registry.apply(1, upsert_nodes=[{"id": "a", "locator": "moved.json"}])
    expected = registry.snapshot()
    registry.close()
    reopened = create(registry.namespace)
    assert reopened.snapshot() == expected
    with pytest.raises(FileExistsError):
        reopened.initialize([], [])
    assert reopened.snapshot() == expected
    assert reopened.server_info()["backend"] == backend


def test_missing_registry_is_not_empty_or_implicitly_created(service):
    backend, create = service
    registry = create()
    with pytest.raises(FileNotFoundError):
        registry.snapshot()
    with pytest.raises(FileNotFoundError):
        registry.apply(1)
    registry.initialize([], [])
    assert registry.snapshot() == {"revision": 1, "nodes": [], "edges": []}


def test_stale_cas_is_checked_inside_real_transaction(service):
    backend, create = service
    registry = create()
    registry.initialize(NODES, [])
    assert registry.apply(1, add_edges=[EDGE]) == 2
    before = registry.snapshot()
    with pytest.raises(RevisionConflict):
        registry.apply(1, upsert_nodes=[{"id": "a", "locator": "stale.json"}])
    assert create(registry.namespace).snapshot() == before


@pytest.mark.parametrize("operation", [
    {"add_edges": [{"source": "b", "target": "a", "kind": "contains"}]},
    {"add_edges": [{"source": "a", "target": "absent", "kind": "contains"}]},
    {"add_edges": [EDGE]},
    {"remove_nodes": ["b"]},
])
def test_invalid_graph_rejects_entire_transaction(service, operation):
    backend, create = service
    registry = create()
    registry.initialize(NODES, [EDGE])
    before = registry.snapshot()
    with pytest.raises(ValueError):
        registry.apply(1, upsert_nodes=[{"id": "a", "locator": "must-not-persist.json"}], **operation)
    assert create(registry.namespace).snapshot() == before


def test_remove_relations_before_node_and_allow_related_cycle(service):
    backend, create = service
    registry = create()
    reverse = {"source": "b", "target": "a", "kind": "related"}
    registry.initialize(NODES, [EDGE])
    assert registry.apply(1, add_edges=[reverse]) == 2
    assert registry.apply(2, remove_edges=[EDGE, reverse], remove_nodes=["b"]) == 3
    assert registry.snapshot() == {"revision": 3, "nodes": [{"id": "a", "locator": "a.json"}], "edges": []}


def test_exception_after_actual_writes_rolls_back(service, monkeypatch):
    backend, create = service
    registry = create()
    registry.initialize(NODES, [])
    before = registry.snapshot()

    def fail(transaction):
        raise RuntimeError("真实事务提交前的故障注入")

    monkeypatch.setattr(registry, "_before_commit", fail)
    with pytest.raises(RuntimeError, match="提交前"):
        registry.apply(1, add_edges=[EDGE], upsert_nodes=[{"id": "a", "locator": "must-rollback.json"}])
    assert create(registry.namespace).snapshot() == before


def test_two_processes_cannot_commit_reverse_edges(service):
    backend, create = service
    registry = create()
    registry.initialize(NODES, [])
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    edges = [EDGE, {"source": "b", "target": "a", "kind": "contains"}]
    processes = [context.Process(target=_reverse_competitor,
                                args=(backend, registry.namespace, edge, ready, start, results)) for edge in edges]
    try:
        for process in processes:
            process.start()
        assert [ready.get(timeout=30) for _ in processes] == ["ready", "ready"]
        start.set()
        outcomes = [results.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert sorted(row[0] for row in outcomes) == ["committed", "conflict_and_cycle_rejected"], outcomes
        snapshot = registry.snapshot()
        validate(snapshot)
        assert snapshot["revision"] == 2 and len(snapshot["edges"]) == 1
    finally:
        start.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
        ready.close()
        results.close()


def test_client_process_termination_discards_uncommitted_writes(service):
    backend, create = service
    registry = create()
    registry.initialize(NODES, [])
    before = registry.snapshot()
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_uncommitted_writer, args=(backend, registry.namespace, ready, release))
    process.start()
    try:
        assert ready.wait(30), "子进程没有到达真实写入后的提交前窗口"
        process.kill()
        process.join(timeout=10)
        assert process.exitcode is not None and process.exitcode != 0
        assert create(registry.namespace).snapshot() == before
        assert registry.apply(1, add_edges=[EDGE]) == 2
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)


def test_concurrent_snapshots_keep_revision_and_content_together(service):
    backend, create = service
    registry = create()
    registry.initialize([{"id": "a", "locator": "1"}], [])

    def writer():
        instance = REGISTRIES[backend](registry.namespace)
        try:
            for revision in range(1, 11):
                instance.apply(revision, upsert_nodes=[{"id": "a", "locator": str(revision + 1)}])
        finally:
            instance.close()

    def reader():
        instance = REGISTRIES[backend](registry.namespace)
        try:
            for _ in range(20):
                current = instance.snapshot()
                assert current["nodes"][0]["locator"] == str(current["revision"])
        finally:
            instance.close()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(writer), executor.submit(reader), executor.submit(reader)]
        for future in futures:
            future.result(timeout=60)
    assert registry.snapshot()["revision"] == 11


@pytest.mark.parametrize("clients", [1, 4, 16])
def test_competing_clients_commit_only_one_expected_revision(service, clients):
    backend, create = service
    registry = create()
    registry.initialize(NODES, [])
    start = threading.Barrier(clients)

    def writer(index):
        instance = REGISTRIES[backend](registry.namespace)
        try:
            assert instance.snapshot()["revision"] == 1
            start.wait(timeout=30)
            try:
                instance.apply(1, upsert_nodes=[{"id": "a", "locator": "writer-{}.json".format(index)}])
                return "committed", index
            except RevisionConflict:
                return "conflict", index
        finally:
            instance.close()

    with ThreadPoolExecutor(max_workers=clients) as executor:
        outcomes = list(executor.map(writer, range(clients)))
    winners = [index for outcome, index in outcomes if outcome == "committed"]
    assert len(winners) == 1
    assert sum(outcome == "conflict" for outcome, _ in outcomes) == clients - 1
    current = registry.snapshot()
    assert current["revision"] == 2
    assert current["nodes"][0]["locator"] == "writer-{}.json".format(winners[0])


def test_logical_backup_roundtrip_preserves_revision_and_refuses_overwrite(service):
    backend, create = service
    source, destination = create(), create()
    source.initialize(NODES, [EDGE])
    source.apply(1, upsert_nodes=[{"id": "a", "locator": "updated.json"}])
    backup = source.logical_backup()
    destination.restore(backup)
    assert destination.snapshot() == source.snapshot()
    with pytest.raises(FileExistsError):
        destination.restore(backup)
    backup["snapshot"]["revision"] += 1
    with pytest.raises(ValueError, match="哈希"):
        create().restore(backup)


def test_native_descendants_match_multiparent_oracle(service):
    backend, create = service
    registry = create()
    nodes = [{"id": node, "locator": node + ".json"} for node in ("a", "b", "c", "d", "outside")]
    edges = [{"source": a, "target": b, "kind": "contains"}
             for a, b in (("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"))]
    edges.append({"source": "a", "target": "outside", "kind": "related"})
    registry.initialize(nodes, edges)
    assert registry.descendants("a") == {"revision": 1, "node_ids": ["a", "b", "c", "d"]}
    assert registry.descendants("b")["node_ids"] == ["b", "d"]
    assert registry.descendants("d")["node_ids"] == ["d"]
    with pytest.raises(ValueError, match="不存在"):
        registry.descendants("missing")


def test_namespaces_do_not_share_nodes_edges_or_revisions(service):
    backend, create = service
    first, second = create(), create()
    first.initialize(NODES, [EDGE])
    second.initialize([{"id": "a", "locator": "second.json"}], [])
    first.apply(1, upsert_nodes=[{"id": "a", "locator": "first.json"}])
    assert first.snapshot()["revision"] == 2
    assert second.snapshot() == {"revision": 1, "nodes": [{"id": "a", "locator": "second.json"}], "edges": []}
    assert second.descendants("a") == {"revision": 1, "node_ids": ["a"]}


@pytest.mark.parametrize("backend", ["postgresql", "neo4j"])
def test_services_require_explicit_sandbox_switch(backend, monkeypatch):
    monkeypatch.delenv("FRONTIER_SERVICE_SANDBOX", raising=False)
    registry = REGISTRIES[backend]("p2_guard")
    with pytest.raises(RuntimeError, match="未启用"):
        registry.snapshot()


@pytest.mark.parametrize("backend,variable,url", [
    ("postgresql", "FRONTIER_PG_DSN", "postgresql://remote.example/test"),
    ("postgresql", "FRONTIER_PG_DSN", "postgresql://127.0.0.1/test?hostaddr=remote.example"),
    ("neo4j", "FRONTIER_NEO4J_URI", "bolt://remote.example:7687"),
    ("neo4j", "FRONTIER_NEO4J_URI", "neo4j://127.0.0.1:7687"),
])
def test_non_loopback_endpoints_are_rejected(backend, variable, url, monkeypatch):
    monkeypatch.setenv("FRONTIER_SERVICE_SANDBOX", "1")
    monkeypatch.setenv(variable, url)
    with pytest.raises(ValueError, match="loopback"):
        REGISTRIES[backend]("p2_guard").snapshot()


@pytest.mark.parametrize("backend", ["postgresql", "neo4j"])
def test_namespace_and_closed_state_are_checked_without_connecting(backend):
    with pytest.raises(ValueError):
        REGISTRIES[backend]("production")
    registry = REGISTRIES[backend]("p2_closed")
    registry.close()
    with pytest.raises(ValueError, match="已关闭"):
        registry.snapshot()
