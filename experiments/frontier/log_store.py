"""实验 F-log：初始快照、校验追加日志及提交水位共同构成关系权威。"""

import errno
import fcntl
import hashlib
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

if __package__:
    from .file_store import CommitUncertainError
    from .storage_common import RevisionConflict, mutated, normalize, validate
else:
    from file_store import CommitUncertainError
    from storage_common import RevisionConflict, mutated, normalize, validate


class CorruptCommittedError(ValueError):
    """已提交权威不完整或校验失败；不能靠截断尾部修复。"""


class UncommittedTailError(ValueError):
    def __init__(self, revision, committed_offset, tail_bytes):
        self.revision, self.committed_offset, self.tail_bytes = revision, committed_offset, tail_bytes
        super().__init__("检测到 {} 字节未提交尾部；已提交版本 {}，请显式 recover_tail 后重读".format(tail_bytes, revision))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def envelope(payload):
    return {"payload": payload, "sha256": digest(payload)}


def decoded(content):
    try:
        value = json.loads(content)
        if (not isinstance(value, dict) or set(value) != {"payload", "sha256"}
                or not isinstance(value["payload"], dict) or digest(value["payload"]) != value["sha256"]):
            raise ValueError("校验不一致")
        return value["payload"], value["sha256"]
    except (ValueError, TypeError, UnicodeDecodeError, KeyError) as error:
        raise CorruptCommittedError("已提交权威校验失败：{}".format(error)) from error


class LogRegistry:
    def __init__(self, path, lock_timeout=5.0):
        if not math.isfinite(lock_timeout) or lock_timeout < 0:
            raise ValueError("锁等待时限必须是非负有限秒数")
        self.path = Path(os.path.abspath(os.fspath(path)))
        self.lock_timeout = lock_timeout
        self._closed = False

    @contextmanager
    def _locked(self, exclusive):
        if self._closed:
            raise ValueError("关系权威已关闭")
        if not self.path.is_dir() or self.path.is_symlink():
            raise FileNotFoundError("F-log 权威目录缺失或不是独立目录")
        descriptor = os.open(str(self.path / "lock"), os.O_RDWR | os.O_CREAT, 0o600)
        deadline, acquired = time.monotonic() + self.lock_timeout, False
        try:
            while True:
                try:
                    fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EINTR):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError("等待 F-log 权威锁超时")
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))
            yield
        finally:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _sync_directory(self):
        descriptor = os.open(str(self.path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _publish_head(self, head):
        descriptor, name = tempfile.mkstemp(prefix=".head-", suffix=".tmp", dir=str(self.path))
        replaced = False
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded(envelope(head)) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, str(self.path / "head.json"))
            replaced = True
            self._sync_directory()
        except OSError as error:
            if replaced:
                raise CommitUncertainError("提交水位已替换但目录持久化未确认；必须重读，禁止盲目重试") from error
            raise
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def initialize(self, nodes, edges):
        if self._closed:
            raise ValueError("关系权威已关闭")
        snapshot = {"revision": 1, "nodes": nodes, "edges": edges}
        validate(snapshot)
        snapshot = normalize(snapshot)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.mkdir(mode=0o700)
        with self._locked(exclusive=True):
            with (self.path / "snapshot.json").open("xb") as stream:
                stream.write(encoded(envelope(snapshot)) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            with (self.path / "journal.log").open("xb") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            base_hash = digest(snapshot)
            self._publish_head({"format": 1, "revision": 1, "committed_offset": 0,
                                "base_sha256": base_hash, "last_record_sha256": base_hash,
                                "state_sha256": base_hash})
        descriptor = os.open(str(self.path.parent), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return snapshot

    def _read(self, allow_tail=False):
        try:
            base, base_hash = decoded((self.path / "snapshot.json").read_bytes())
            head, _ = decoded((self.path / "head.json").read_bytes())
            if (head.get("format") != 1 or type(head.get("committed_offset")) is not int
                    or head["committed_offset"] < 0 or head.get("base_sha256") != base_hash
                    or type(head.get("revision")) is not int):
                raise CorruptCommittedError("提交水位字段或初始快照关联无效")
            validate(base)
            journal = (self.path / "journal.log").read_bytes()
            offset = head["committed_offset"]
            if len(journal) < offset:
                raise CorruptCommittedError("已确认日志前缀被截短，禁止恢复为旧版本")
            committed = journal[:offset]
            if committed and not committed.endswith(b"\n"):
                raise CorruptCommittedError("已提交日志边界不是完整记录")
            nodes = {node["id"]: node for node in base["nodes"]}
            edges = {(edge["source"], edge["target"], edge["kind"]): edge for edge in base["edges"]}
            revision, previous_hash = base["revision"], base_hash
            for line in committed.splitlines():
                record, record_hash = decoded(line)
                if record.get("previous_sha256") != previous_hash or record.get("revision") != revision + 1:
                    raise CorruptCommittedError("追加日志的校验链或版本次序无效")
                operations = record["operations"]
                for node_id in operations["remove_nodes"]:
                    del nodes[node_id]
                for node in operations["upsert_nodes"]:
                    nodes[node["id"]] = node
                for edge in operations["remove_edges"]:
                    edges.pop((edge["source"], edge["target"], edge["kind"]), None)
                for edge in operations["add_edges"]:
                    identity = (edge["source"], edge["target"], edge["kind"])
                    if identity in edges:
                        raise CorruptCommittedError("日志包含重复边")
                    edges[identity] = edge
                revision, previous_hash = record["revision"], record_hash
            snapshot = {"revision": revision, "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
                        "edges": [edges[key] for key in sorted(edges)]}
            validate(snapshot)
            if (revision != head["revision"] or previous_hash != head.get("last_record_sha256")
                    or digest(snapshot) != head.get("state_sha256")):
                raise CorruptCommittedError("提交水位与重放结果不一致，禁止退回旧版本")
            tail = journal[offset:]
            if tail and not allow_tail:
                raise UncommittedTailError(revision, offset, len(tail))
            return snapshot, head, tail
        except (UncommittedTailError, CorruptCommittedError):
            raise
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise CorruptCommittedError("F-log 权威读取失败：{}".format(error)) from error

    def snapshot(self):
        with self._locked(exclusive=False):
            return self._read()[0]

    def _append_record(self, content):
        with (self.path / "journal.log").open("ab") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def apply(self, expected_revision, upsert_nodes=None, add_edges=None, remove_edges=None, remove_nodes=None):
        with self._locked(exclusive=True):
            snapshot, head, _ = self._read()
            updated = mutated(snapshot, expected_revision, upsert_nodes, add_edges, remove_edges, remove_nodes)
            record = {"revision": updated["revision"], "previous_sha256": head["last_record_sha256"],
                      "operations": {"upsert_nodes": upsert_nodes or [], "add_edges": add_edges or [],
                                     "remove_edges": remove_edges or [], "remove_nodes": remove_nodes or []}}
            content = encoded(envelope(record)) + b"\n"
            updated_head = {"format": 1, "revision": updated["revision"],
                            "committed_offset": head["committed_offset"] + len(content),
                            "base_sha256": head["base_sha256"], "last_record_sha256": digest(record),
                            "state_sha256": digest(updated)}
            try:
                self._append_record(content)
                self._publish_head(updated_head)
            except CommitUncertainError:
                raise
            except OSError as error:
                raise CommitUncertainError("追加或提交失败；必须读取提交水位检查尾部，禁止自动重试") from error
            return updated["revision"]

    def recover_tail(self):
        with self._locked(exclusive=True):
            snapshot, head, tail = self._read(allow_tail=True)
            result = {"revision": snapshot["revision"], "committed_offset": head["committed_offset"],
                      "removed_uncommitted_bytes": len(tail), "quarantine": None}
            if not tail:
                return result
            descriptor, name = tempfile.mkstemp(prefix="quarantine-tail-", suffix=".bin", dir=str(self.path))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(tail)
                stream.flush()
                os.fsync(stream.fileno())
            self._sync_directory()
            with (self.path / "journal.log").open("r+b") as stream:
                stream.truncate(head["committed_offset"])
                stream.flush()
                os.fsync(stream.fileno())
            result.update({"quarantine": name, "tail_sha256": hashlib.sha256(tail).hexdigest()})
            return result

    def close(self):
        self._closed = True
