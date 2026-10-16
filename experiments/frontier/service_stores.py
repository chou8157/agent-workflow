"""P2 专用 PostgreSQL/Neo4j 关系权威；只允许显式启用的本机隔离实例。"""

import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlparse

if __package__:
    from .storage_common import RevisionConflict, mutated, normalize, validate
else:
    from storage_common import RevisionConflict, mutated, normalize, validate


class ServiceCommitUncertainError(OSError):
    """服务端提交确认丢失；必须重读，不可盲目重试。"""


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def configured(backend):
    required = ("FRONTIER_PG_DSN",) if backend == "postgresql" else (
        "FRONTIER_NEO4J_URI", "FRONTIER_NEO4J_USER", "FRONTIER_NEO4J_PASSWORD")
    return os.environ.get("FRONTIER_SERVICE_SANDBOX") == "1" and all(os.environ.get(key) for key in required)


def _endpoint(variable, schemes):
    if os.environ.get("FRONTIER_SERVICE_SANDBOX") != "1":
        raise RuntimeError("服务实验未启用：需要 FRONTIER_SERVICE_SANDBOX=1")
    value = os.environ.get(variable, "")
    parsed = urlparse(value)
    if parsed.scheme not in schemes or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("服务实验仅接受显式配置的 loopback URL：" + variable)
    if {key for key, _ in parse_qsl(parsed.query)} & {"host", "hostaddr", "port", "service", "servicefile"}:
        raise ValueError("服务实验不接受覆盖 loopback 目标的连接参数")
    return value


class _Registry:
    def __init__(self, namespace):
        if not isinstance(namespace, str) or not re.fullmatch(r"p2_[a-z0-9_]{1,100}", namespace):
            raise ValueError("服务关系权威名称必须为 p2_ 开头的小写实验标识")
        self.namespace = namespace
        self._closed = False
        self._local_lock = threading.RLock()

    def _check_open(self):
        if self._closed:
            raise ValueError("关系权威已关闭")

    def initialize(self, nodes, edges):
        value = {"revision": 1, "nodes": nodes, "edges": edges}
        validate(value)
        return self._initialize_snapshot(normalize(value))

    def logical_backup(self):
        value = self.snapshot()
        return {"format": "frontier-registry-v1", "snapshot": value,
                "sha256": hashlib.sha256(_encoded(value)).hexdigest()}

    def restore(self, backup):
        if not isinstance(backup, dict) or backup.get("format") != "frontier-registry-v1":
            raise ValueError("逻辑备份格式不受支持")
        value = backup.get("snapshot")
        validate(value)
        if hashlib.sha256(_encoded(value)).hexdigest() != backup.get("sha256"):
            raise ValueError("逻辑备份内容哈希不符")
        return self._initialize_snapshot(normalize(value))

    def _before_commit(self, transaction):
        """故障探针注入点：实际数据已写入，事务尚未提交。"""


class PostgreSQLRegistry(_Registry):
    backend = "postgresql"

    def __init__(self, namespace):
        super().__init__(namespace)
        self._connection = None
        self._psycopg = None

    def _connect(self):
        self._check_open()
        if self._connection is None or self._connection.closed:
            dsn = _endpoint("FRONTIER_PG_DSN", ("postgresql", "postgres"))
            try:
                import psycopg
            except ImportError as error:
                raise RuntimeError("缺少 psycopg 驱动；服务候选未运行") from error
            self._psycopg = psycopg
            hostaddr = "::1" if urlparse(dsn).hostname == "::1" else "127.0.0.1"
            self._connection = psycopg.connect(dsn, hostaddr=hostaddr, connect_timeout=5)
        return self._connection

    @contextmanager
    def _transaction(self, readonly=False):
        with self._local_lock:
            connection = self._connect()
            try:
                if readonly:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout = '5s'")
                connection.execute("SET LOCAL statement_timeout = '15s'")
                connection.execute("SET LOCAL synchronous_commit = 'on'")
                yield connection
                try:
                    connection.commit()
                except self._psycopg.OperationalError as error:
                    raise ServiceCommitUncertainError("PostgreSQL 提交确认失败，请重读关系版本，禁止自动重试") from error
            except BaseException:
                try:
                    connection.rollback()
                except Exception:
                    pass
                raise

    @staticmethod
    def _many(connection, statement, rows):
        if rows:
            with connection.cursor() as cursor:
                cursor.executemany(statement, rows)

    @staticmethod
    def _schema(connection):
        connection.execute("SELECT pg_advisory_xact_lock(2026101001)")
        statements = [
            "CREATE TABLE IF NOT EXISTS frontier_registries (registry TEXT PRIMARY KEY, revision BIGINT NOT NULL CHECK(revision>=1))",
            "CREATE TABLE IF NOT EXISTS frontier_nodes (registry TEXT NOT NULL REFERENCES frontier_registries(registry) ON DELETE CASCADE, "
            "id TEXT NOT NULL CHECK(length(id)>0), locator TEXT NOT NULL CHECK(length(locator)>0), PRIMARY KEY(registry,id))",
            "CREATE TABLE IF NOT EXISTS frontier_edges (registry TEXT NOT NULL REFERENCES frontier_registries(registry) ON DELETE CASCADE, "
            "source TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('contains','related')), "
            "PRIMARY KEY(registry,source,target,kind), FOREIGN KEY(registry,source) REFERENCES frontier_nodes(registry,id), "
            "FOREIGN KEY(registry,target) REFERENCES frontier_nodes(registry,id))",
            "CREATE INDEX IF NOT EXISTS frontier_edges_target ON frontier_edges(registry,target,kind)",
        ]
        for statement in statements:
            connection.execute(statement)

    def _revision(self, connection, locking=False):
        if connection.execute("SELECT to_regclass('frontier_registries')").fetchone()[0] is None:
            raise FileNotFoundError("PostgreSQL 实验关系权威未初始化")
        suffix = " FOR UPDATE" if locking else ""
        row = connection.execute("SELECT revision FROM frontier_registries WHERE registry=%s" + suffix,
                                 (self.namespace,)).fetchone()
        if row is None:
            raise FileNotFoundError("PostgreSQL 实验关系权威不存在")
        return row[0]

    def _read(self, connection, revision=None):
        if revision is None:
            revision = self._revision(connection)
        nodes = [{"id": row[0], "locator": row[1]} for row in connection.execute(
            "SELECT id,locator FROM frontier_nodes WHERE registry=%s ORDER BY id", (self.namespace,))]
        edges = [{"source": row[0], "target": row[1], "kind": row[2]} for row in connection.execute(
            "SELECT source,target,kind FROM frontier_edges WHERE registry=%s ORDER BY source,target,kind", (self.namespace,))]
        value = {"revision": revision, "nodes": nodes, "edges": edges}
        validate(value)
        return normalize(value)

    def _initialize_snapshot(self, value):
        with self._transaction() as connection:
            self._schema(connection)
            if connection.execute("SELECT 1 FROM frontier_registries WHERE registry=%s", (self.namespace,)).fetchone():
                raise FileExistsError("关系权威已存在，拒绝覆盖初始化/恢复")
            connection.execute("INSERT INTO frontier_registries VALUES (%s,%s)", (self.namespace, value["revision"]))
            self._many(connection, "INSERT INTO frontier_nodes VALUES (%s,%s,%s)",
                       [(self.namespace, node["id"], node["locator"]) for node in value["nodes"]])
            self._many(connection, "INSERT INTO frontier_edges VALUES (%s,%s,%s,%s)",
                       [(self.namespace, edge["source"], edge["target"], edge["kind"]) for edge in value["edges"]])
            self._before_commit(connection)
        return value

    def snapshot(self):
        with self._transaction(readonly=True) as connection:
            return self._read(connection)

    def apply(self, expected_revision, upsert_nodes=None, add_edges=None, remove_edges=None, remove_nodes=None):
        with self._transaction() as connection:
            revision = self._revision(connection, locking=True)
            old = self._read(connection, revision)
            new = mutated(old, expected_revision, upsert_nodes, add_edges, remove_edges, remove_nodes)
            old_nodes = {node["id"]: node["locator"] for node in old["nodes"]}
            new_nodes = {node["id"]: node["locator"] for node in new["nodes"]}
            old_edges = {(edge["source"], edge["target"], edge["kind"]) for edge in old["edges"]}
            new_edges = {(edge["source"], edge["target"], edge["kind"]) for edge in new["edges"]}
            self._many(connection, "DELETE FROM frontier_edges WHERE registry=%s AND source=%s AND target=%s AND kind=%s",
                       [(self.namespace,) + edge for edge in sorted(old_edges - new_edges)])
            self._many(connection, "DELETE FROM frontier_nodes WHERE registry=%s AND id=%s",
                       [(self.namespace, key) for key in sorted(old_nodes.keys() - new_nodes.keys())])
            self._many(connection, "INSERT INTO frontier_nodes VALUES (%s,%s,%s)",
                       [(self.namespace, key, new_nodes[key]) for key in sorted(new_nodes.keys() - old_nodes.keys())])
            self._many(connection, "UPDATE frontier_nodes SET locator=%s WHERE registry=%s AND id=%s",
                       [(new_nodes[key], self.namespace, key) for key in sorted(old_nodes.keys() & new_nodes.keys())
                        if old_nodes[key] != new_nodes[key]])
            self._many(connection, "INSERT INTO frontier_edges VALUES (%s,%s,%s,%s)",
                       [(self.namespace,) + edge for edge in sorted(new_edges - old_edges)])
            connection.execute("UPDATE frontier_registries SET revision=%s WHERE registry=%s",
                               (new["revision"], self.namespace))
            self._before_commit(connection)
        return new["revision"]

    def descendants(self, root_id):
        with self._transaction(readonly=True) as connection:
            revision = self._revision(connection)
            rows = connection.execute(
                "WITH RECURSIVE descendants(id) AS ("
                "SELECT id FROM frontier_nodes WHERE registry=%s AND id=%s UNION "
                "SELECT e.target FROM frontier_edges e JOIN descendants d ON e.source=d.id "
                "WHERE e.registry=%s AND e.kind='contains') SELECT id FROM descendants ORDER BY id",
                (self.namespace, root_id, self.namespace)).fetchall()
            if not rows:
                raise ValueError("查询根节点不存在")
            return {"revision": revision, "node_ids": [row[0] for row in rows]}

    def server_info(self):
        with self._transaction(readonly=True) as connection:
            version = connection.execute("SELECT version()").fetchone()[0]
            synchronous = connection.execute("SHOW synchronous_commit").fetchone()[0]
        return {"backend": self.backend, "version": version, "synchronous_commit": synchronous,
                "snapshot_strategy": "repeatable_read", "driver": self._psycopg.__version__}

    def delete_test_registry(self):
        with self._transaction() as connection:
            self._revision(connection, locking=True)
            connection.execute("DELETE FROM frontier_registries WHERE registry=%s", (self.namespace,))

    def close(self):
        with self._local_lock:
            if self._connection is not None:
                self._connection.close()
            self._closed = True


class Neo4jRegistry(_Registry):
    backend = "neo4j"

    def __init__(self, namespace):
        super().__init__(namespace)
        self._driver = None
        self._neo4j = None

    def _connect(self):
        self._check_open()
        if self._driver is None:
            uri = _endpoint("FRONTIER_NEO4J_URI", ("bolt",))
            try:
                import neo4j
            except ImportError as error:
                raise RuntimeError("缺少 neo4j 驱动；服务候选未运行") from error
            user, password = os.environ.get("FRONTIER_NEO4J_USER"), os.environ.get("FRONTIER_NEO4J_PASSWORD")
            if not user or not password:
                raise ValueError("缺少 Neo4j 专用实例凭据")
            self._neo4j = neo4j
            self._driver = neo4j.GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5,
                                                     max_connection_pool_size=4, max_transaction_retry_time=0)
        return self._driver

    @contextmanager
    def _transaction(self):
        with self._local_lock:
            driver = self._connect()
            with driver.session(database=os.environ.get("FRONTIER_NEO4J_DATABASE", "neo4j")) as session:
                with session.begin_transaction(timeout=15) as transaction:
                    try:
                        yield transaction
                        try:
                            transaction.commit()
                        except (self._neo4j.exceptions.ServiceUnavailable, self._neo4j.exceptions.SessionExpired) as error:
                            raise ServiceCommitUncertainError("Neo4j 提交确认失败，请重读关系版本，禁止自动重试") from error
                    except BaseException:
                        try:
                            transaction.rollback()
                        except Exception:
                            pass
                        raise

    def _schema(self):
        for statement in (
            "CREATE CONSTRAINT frontier_registry_id IF NOT EXISTS FOR (r:FrontierRegistry) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT frontier_node_id IF NOT EXISTS FOR (n:FrontierNode) REQUIRE (n.registry,n.id) IS UNIQUE",
        ):
            with self._transaction() as transaction:
                transaction.run(statement).consume()

    def _revision(self, transaction):
        # Community 的一致快照使用元节点锁；属性写后即删，但仍要求写事务权限。
        row = transaction.run(
            "MATCH (r:FrontierRegistry {id:$registry}) SET r.__frontier_lock=true "
            "REMOVE r.__frontier_lock RETURN r.revision AS revision", registry=self.namespace).single()
        if row is None:
            raise FileNotFoundError("Neo4j 实验关系权威不存在")
        return row["revision"]

    def _read(self, transaction, revision):
        nodes = [dict(row) for row in transaction.run(
            "MATCH (n:FrontierNode {registry:$registry}) RETURN n.id AS id,n.locator AS locator ORDER BY id",
            registry=self.namespace)]
        edges = [dict(row) for row in transaction.run(
            "MATCH (a:FrontierNode {registry:$registry})-[r:FRONTIER_CONTAINS|FRONTIER_RELATED]->"
            "(b:FrontierNode {registry:$registry}) RETURN a.id AS source,b.id AS target,"
            "CASE type(r) WHEN 'FRONTIER_CONTAINS' THEN 'contains' ELSE 'related' END AS kind "
            "ORDER BY source,target,kind", registry=self.namespace)]
        value = {"revision": revision, "nodes": nodes, "edges": edges}
        validate(value)
        return normalize(value)

    def _put_nodes(self, transaction, nodes):
        if nodes:
            transaction.run("UNWIND $nodes AS row MERGE (n:FrontierNode {registry:$registry,id:row.id}) "
                            "SET n.locator=row.locator", registry=self.namespace, nodes=nodes).consume()

    def _put_edges(self, transaction, edges):
        for kind, label in (("contains", "FRONTIER_CONTAINS"), ("related", "FRONTIER_RELATED")):
            rows = [edge for edge in edges if edge["kind"] == kind]
            if rows:
                transaction.run(
                    "UNWIND $edges AS row MATCH (a:FrontierNode {registry:$registry,id:row.source}),"
                    "(b:FrontierNode {registry:$registry,id:row.target}) CREATE (a)-[:" + label + "]->(b)",
                    registry=self.namespace, edges=rows).consume()

    def _initialize_snapshot(self, value):
        self._schema()
        token = uuid.uuid4().hex
        with self._transaction() as transaction:
            row = transaction.run(
                "MERGE (r:FrontierRegistry {id:$registry}) "
                "ON CREATE SET r.revision=$revision,r.__initialization_token=$token "
                "SET r.__frontier_lock=true REMOVE r.__frontier_lock "
                "RETURN r.__initialization_token AS token", registry=self.namespace,
                revision=value["revision"], token=token).single()
            if row["token"] != token:
                raise FileExistsError("关系权威已存在，拒绝覆盖初始化/恢复")
            self._put_nodes(transaction, value["nodes"])
            self._put_edges(transaction, value["edges"])
            transaction.run("MATCH (r:FrontierRegistry {id:$registry}) SET r.revision=$revision REMOVE r.__initialization_token",
                            registry=self.namespace, revision=value["revision"]).consume()
            self._before_commit(transaction)
        return value

    def snapshot(self):
        with self._transaction() as transaction:
            return self._read(transaction, self._revision(transaction))

    def apply(self, expected_revision, upsert_nodes=None, add_edges=None, remove_edges=None, remove_nodes=None):
        with self._transaction() as transaction:
            old = self._read(transaction, self._revision(transaction))
            new = mutated(old, expected_revision, upsert_nodes, add_edges, remove_edges, remove_nodes)
            old_nodes = {node["id"]: node for node in old["nodes"]}
            new_nodes = {node["id"]: node for node in new["nodes"]}
            old_edges = {(edge["source"], edge["target"], edge["kind"]) for edge in old["edges"]}
            new_edges = {(edge["source"], edge["target"], edge["kind"]) for edge in new["edges"]}
            for kind, label in (("contains", "FRONTIER_CONTAINS"), ("related", "FRONTIER_RELATED")):
                removed = [{"source": source, "target": target} for source, target, edge_kind in old_edges - new_edges
                           if edge_kind == kind]
                if removed:
                    transaction.run("UNWIND $edges AS row MATCH (a:FrontierNode {registry:$registry,id:row.source})"
                                    "-[r:" + label + "]->(b:FrontierNode {registry:$registry,id:row.target}) DELETE r",
                                    registry=self.namespace, edges=removed).consume()
            removed_nodes = sorted(old_nodes.keys() - new_nodes.keys())
            if removed_nodes:
                transaction.run("UNWIND $ids AS id MATCH (n:FrontierNode {registry:$registry,id:id}) DELETE n",
                                registry=self.namespace, ids=removed_nodes).consume()
            self._put_nodes(transaction, [new_nodes[key] for key in sorted(new_nodes)
                                          if old_nodes.get(key) != new_nodes[key]])
            self._put_edges(transaction, [{"source": source, "target": target, "kind": kind}
                                          for source, target, kind in sorted(new_edges - old_edges)])
            transaction.run("MATCH (r:FrontierRegistry {id:$registry}) SET r.revision=$revision",
                            registry=self.namespace, revision=new["revision"]).consume()
            self._before_commit(transaction)
        return new["revision"]

    def descendants(self, root_id):
        with self._transaction() as transaction:
            revision = self._revision(transaction)
            rows = transaction.run(
                "MATCH (root:FrontierNode {registry:$registry,id:$root})"
                "-[:FRONTIER_CONTAINS*0..]->(node:FrontierNode) "
                "WHERE node.registry=$registry RETURN DISTINCT node.id AS id ORDER BY id",
                registry=self.namespace, root=root_id)
            ids = [row["id"] for row in rows]
            if not ids:
                raise ValueError("查询根节点不存在")
            return {"revision": revision, "node_ids": ids}

    def server_info(self):
        with self._transaction() as transaction:
            row = transaction.run("CALL dbms.components() YIELD name,versions,edition RETURN name,versions,edition").single()
        return {"backend": self.backend, "name": row["name"], "version": row["versions"], "edition": row["edition"],
                "driver": self._neo4j.__version__, "snapshot_strategy": "registry_node_lock_requires_write_transaction"}

    def delete_test_registry(self):
        with self._transaction() as transaction:
            self._revision(transaction)
            transaction.run("MATCH (n:FrontierNode {registry:$registry}) DETACH DELETE n", registry=self.namespace).consume()
            transaction.run("MATCH (r:FrontierRegistry {id:$registry}) DELETE r", registry=self.namespace).consume()

    def close(self):
        with self._local_lock:
            if self._driver is not None:
                self._driver.close()
            self._closed = True


REGISTRIES = {"postgresql": PostgreSQLRegistry, "neo4j": Neo4jRegistry}
