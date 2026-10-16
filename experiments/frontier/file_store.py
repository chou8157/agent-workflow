"""本机 POSIX 文件关系权威；不支持网络文件系统或绕过锁的外部写入。"""

import errno
import fcntl
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

if __package__:
    from .storage_common import RevisionConflict, mutated, normalize, validate
else:
    from storage_common import RevisionConflict, mutated, normalize, validate


class CommitUncertainError(OSError):
    """文件已替换，但持久化确认失败；调用方必须重读，不能自动重试。"""


class FileRegistry:
    def __init__(self, path, lock_timeout=5.0):
        if not math.isfinite(lock_timeout) or lock_timeout < 0:
            raise ValueError("锁等待时限必须为非负有限秒数")
        self.path = Path(os.path.abspath(os.fspath(path)))
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.lock_timeout = lock_timeout
        self._closed = False

    @contextmanager
    def _locked(self, exclusive):
        if self._closed:
            raise ValueError("关系权威已关闭")
        descriptor = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        acquired = False
        deadline = time.monotonic() + self.lock_timeout
        operation = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        try:
            while True:
                try:
                    fcntl.flock(descriptor, operation)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EINTR):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("等待关系权威文件锁超时") from exc
                    time.sleep(min(0.01, remaining))
            yield
        finally:
            try:
                if acquired:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _read(self):
        if self.path.is_symlink():
            raise ValueError("关系权威路径不能为符号链接")
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("关系权威文件损坏，无法读取快照") from exc
        if not isinstance(value, dict):
            raise ValueError("关系快照必须为对象")
        validate(value)
        return normalize(value)

    def _write(self, value):
        # 锁文件独立存在，避免替换数据文件后不同进程锁住不同 inode。
        descriptor, temporary = tempfile.mkstemp(
            prefix="." + self.path.name + ".", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            directory = os.open(str(self.path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.replace(temporary, str(self.path))
                try:
                    os.fsync(directory)
                except OSError as exc:
                    raise CommitUncertainError(
                        "关系文件已替换，但目录持久化确认失败；提交结果不确定，请重读后决定，禁止自动重试"
                    ) from exc
            finally:
                os.close(directory)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def initialize(self, nodes, edges):
        if self._closed:
            raise ValueError("关系权威已关闭")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked(exclusive=True):
            if os.path.lexists(str(self.path)):
                raise FileExistsError("关系权威已存在，拒绝覆盖初始化")
            value = {"revision": 1, "nodes": nodes, "edges": edges}
            validate(value)
            value = normalize(value)
            self._write(value)
            return value

    def snapshot(self):
        with self._locked(exclusive=False):
            return self._read()

    def apply(self, expected_revision, upsert_nodes=None, add_edges=None, remove_edges=None, remove_nodes=None):
        with self._locked(exclusive=True):
            value = mutated(
                self._read(), expected_revision, upsert_nodes, add_edges, remove_edges, remove_nodes
            )
            self._write(value)
            return value["revision"]

    def close(self):
        self._closed = True
