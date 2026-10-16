"""SQLite 关系权威原型；只在显式初始化时创建数据库。"""

import os
import sqlite3
import threading
from pathlib import Path

if __package__:
    from .storage_common import RevisionConflict, mutated, normalize, validate
else:
    from storage_common import RevisionConflict, mutated, normalize, validate


class SQLiteRegistry:
    BUSY_TIMEOUT_MS = 5000

    def __init__(self, path):
        self.path = Path(path).resolve()
        self._lock = threading.RLock()
        self._closed = False

    def _check_open(self):
        if self._closed:
            raise ValueError("关系库实例已关闭")

    def _connect(self, readonly=False, initializing=False):
        self._check_open()
        if not self.path.is_file():
            raise FileNotFoundError("关系权威不存在：{}".format(self.path))
        mode = "ro" if readonly else "rw"
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=" + mode,
            uri=True,
            isolation_level=None,
            timeout=self.BUSY_TIMEOUT_MS / 1000,
        )
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout={}".format(self.BUSY_TIMEOUT_MS))
            connection.execute("PRAGMA synchronous=FULL")
            if initializing:
                journal = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            else:
                journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
            if journal.lower() != "wal":
                raise ValueError("关系库未使用已约定的 WAL 持久化模式")
            return connection
        except Exception:
            connection.close()
            raise

    @staticmethod
    def _read_snapshot(connection):
        metadata = connection.execute("SELECT singleton, revision, schema_version FROM meta").fetchall()
        if len(metadata) != 1 or metadata[0][0] != 1 or metadata[0][2] != 1:
            raise ValueError("关系权威元数据缺失或版本不受支持")
        snapshot = {
            "revision": metadata[0][1],
            "nodes": [{"id": row[0], "locator": row[1]} for row in connection.execute(
                "SELECT id, locator FROM nodes ORDER BY id"
            )],
            "edges": [{"source": row[0], "target": row[1], "kind": row[2]} for row in connection.execute(
                "SELECT source, target, kind FROM edges ORDER BY source, target, kind"
            )],
        }
        validate(snapshot)
        return snapshot

    def initialize(self, nodes, edges):
        initial = {"revision": 1, "nodes": nodes, "edges": edges}
        validate(initial)
        initial = normalize(initial)
        with self._lock:
            self._check_open()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as error:
                raise ValueError("关系权威已存在，拒绝覆盖") from error
            os.close(descriptor)
            connection = None
            try:
                connection = self._connect(initializing=True)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                    "revision INTEGER NOT NULL CHECK(revision>=1), "
                    "schema_version INTEGER NOT NULL CHECK(schema_version=1))"
                )
                connection.execute(
                    "CREATE TABLE nodes (id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), "
                    "locator TEXT NOT NULL CHECK(length(locator)>0)) WITHOUT ROWID"
                )
                connection.execute(
                    "CREATE TABLE edges (source TEXT NOT NULL REFERENCES nodes(id), "
                    "target TEXT NOT NULL REFERENCES nodes(id), "
                    "kind TEXT NOT NULL CHECK(kind IN ('contains','related')), "
                    "PRIMARY KEY(source,target,kind)) WITHOUT ROWID"
                )
                connection.execute("CREATE INDEX edges_target ON edges(target)")
                connection.execute("INSERT INTO meta VALUES (1,1,1)")
                connection.executemany("INSERT INTO nodes(id,locator) VALUES (?,?)", [
                    (node["id"], node["locator"]) for node in initial["nodes"]
                ])
                connection.executemany("INSERT INTO edges(source,target,kind) VALUES (?,?,?)", [
                    (edge["source"], edge["target"], edge["kind"]) for edge in initial["edges"]
                ])
                connection.commit()
            except Exception:
                if connection is not None:
                    connection.rollback()
                # 保留失败初始化文件作为显式故障，不把空文件当作可覆盖权威。
                raise
            finally:
                if connection is not None:
                    connection.close()

    def snapshot(self):
        with self._lock:
            connection = None
            try:
                connection = self._connect(readonly=True)
                connection.execute("BEGIN")
                value = self._read_snapshot(connection)
                connection.commit()
                return value
            except sqlite3.Error as error:
                raise ValueError("SQLite 关系权威读取失败：{}".format(error)) from error
            finally:
                if connection is not None:
                    connection.close()

    def apply(self, expected_revision, upsert_nodes=None, add_edges=None,
              remove_edges=None, remove_nodes=None):
        with self._lock:
            connection = None
            try:
                connection = self._connect()
                connection.execute("BEGIN IMMEDIATE")
                previous = self._read_snapshot(connection)
                updated = mutated(previous, expected_revision, upsert_nodes, add_edges,
                                  remove_edges, remove_nodes)
                old_nodes = {node["id"]: node["locator"] for node in previous["nodes"]}
                new_nodes = {node["id"]: node["locator"] for node in updated["nodes"]}
                old_edges = {(edge["source"], edge["target"], edge["kind"]) for edge in previous["edges"]}
                new_edges = {(edge["source"], edge["target"], edge["kind"]) for edge in updated["edges"]}
                # 先移除边，再更新节点，最后添加边，保持每条 SQL 的外键约束成立。
                connection.executemany("DELETE FROM edges WHERE source=? AND target=? AND kind=?",
                                       sorted(old_edges - new_edges))
                connection.executemany("DELETE FROM nodes WHERE id=?",
                                       [(key,) for key in sorted(old_nodes.keys() - new_nodes.keys())])
                connection.executemany("INSERT INTO nodes(id,locator) VALUES (?,?)", [
                    (key, new_nodes[key]) for key in sorted(new_nodes.keys() - old_nodes.keys())
                ])
                connection.executemany("UPDATE nodes SET locator=? WHERE id=?", [
                    (new_nodes[key], key) for key in sorted(new_nodes.keys() & old_nodes.keys())
                    if new_nodes[key] != old_nodes[key]
                ])
                connection.executemany("INSERT INTO edges(source,target,kind) VALUES (?,?,?)",
                                       sorted(new_edges - old_edges))
                changed = connection.execute(
                    "UPDATE meta SET revision=? WHERE singleton=1 AND revision=?",
                    (updated["revision"], expected_revision),
                )
                if changed.rowcount != 1:
                    raise RevisionConflict("关系版本已变化，请重新读取后重试")
                connection.commit()
                return updated["revision"]
            except Exception as error:
                if connection is not None:
                    connection.rollback()
                if isinstance(error, sqlite3.Error):
                    raise ValueError("SQLite 关系更新失败：{}".format(error)) from error
                raise
            finally:
                if connection is not None:
                    connection.close()

    def close(self):
        with self._lock:
            self._closed = True
