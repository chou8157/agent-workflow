"""真实多进程竞争及故障注入下，本地状态和活动事实不得丢失。"""

import json
import multiprocessing
import os
import signal
import stat
from contextlib import contextmanager
from pathlib import Path

import pytest

from experiments.frontier import activity_closeout, node_workflow as workflow
from experiments.frontier.test_activity_closeout import _item, _payload
from experiments.frontier.test_mvp_light import _copy_network


PROCESS_TIMEOUT = 15


def _writer(project, item_id, payload, operation, results, barrier=None,
            attempted=None, before_replace=None, resume=None, lock_timeout=5.0):
    """所有注入均在独立进程中，避免影响其他测试的文件操作。"""
    try:
        original_lock = workflow._stable.state_lock

        @contextmanager
        def observed_lock(path, *args, **kwargs):
            if attempted is not None:
                attempted.set()
            with original_lock(path, *args, **kwargs):
                yield

        workflow._stable.state_lock = observed_lock
        if before_replace is not None:
            original_replace = workflow._stable.os.replace

            def pause_before_replace(source, destination):
                before_replace.set()
                if not resume.wait(PROCESS_TIMEOUT):
                    raise RuntimeError("测试等待释放写入超时")
                original_replace(source, destination)

            workflow._stable.os.replace = pause_before_replace
        if barrier is not None:
            barrier.wait(timeout=PROCESS_TIMEOUT)
        if operation == "activity":
            result = activity_closeout.append_activity(
                Path(project), item_id, payload, lock_timeout=lock_timeout)
        else:
            workflow._stable.set_status(Path(project), item_id, "in_progress")
            result = {"status": "in_progress"}
        results.put({"ok": True, "result": result})
    except BaseException as error:
        results.put({"ok": False, "type": type(error).__name__, "message": str(error),
                     "value_error": isinstance(error, ValueError)})


def _holder(state_path, acquired, release):
    with workflow._stable.state_lock(Path(state_path)):
        acquired.set()
        if not release.wait(PROCESS_TIMEOUT):
            raise RuntimeError("测试等待释放锁超时")


@contextmanager
def _children():
    context = multiprocessing.get_context("spawn")
    processes = []

    def start(target, *args, **kwargs):
        process = context.Process(target=target, args=args, kwargs=kwargs)
        processes.append(process)
        process.start()
        return process

    try:
        yield context, start
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
            process.join(timeout=PROCESS_TIMEOUT)


def _result(process, results):
    value = results.get(timeout=PROCESS_TIMEOUT)
    process.join(timeout=PROCESS_TIMEOUT)
    assert process.exitcode == 0, "子进程未正常完成"
    return value


def _state(item):
    return json.loads((item / ".state.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("same_id", [False, True], ids=["different_ids", "same_id"])
def test_concurrent_processes_preserve_activities_and_idempotency(tmp_path, same_id):
    nodes, _ = _copy_network(tmp_path)
    item = _item(nodes, "leaf")
    state_path = item / ".state.json"
    count = 4
    with _children() as (context, start):
        barrier = context.Barrier(count + 1)
        attempts = [context.Event() for _ in range(count)]
        queues = [context.Queue() for _ in range(count)]
        with workflow._stable.state_lock(state_path):
            processes = [
                start(_writer, nodes / "leaf", item.name,
                      _payload(nodes, "leaf", "same" if same_id else "a-{}".format(index)),
                      "activity", queues[index], barrier=barrier, attempted=attempts[index])
                for index in range(count)
            ]
            barrier.wait(timeout=PROCESS_TIMEOUT)
            assert all(event.wait(PROCESS_TIMEOUT) for event in attempts)
        results = [_result(process, queue) for process, queue in zip(processes, queues)]

    assert all(result["ok"] for result in results), results
    statuses = [result["result"]["status"] for result in results]
    records = _state(item)["activity_records"]
    if same_id:
        assert statuses.count("created") == 1
        assert statuses.count("unchanged") == count - 1
        assert [record["id"] for record in records] == ["same"]
    else:
        assert statuses == ["created"] * count
        assert {record["id"] for record in records} == {"a-{}".format(index) for index in range(count)}
        assert len(records) == count


@pytest.mark.parametrize("first_operation", ["activity", "status"])
def test_status_and_activity_writers_do_not_overwrite_each_other(tmp_path, first_operation):
    nodes, _ = _copy_network(tmp_path)
    item = _item(nodes, "leaf")
    payload = _payload(nodes, "leaf")
    second_operation = "status" if first_operation == "activity" else "activity"
    with _children() as (context, start):
        before_replace, resume, second_attempt = context.Event(), context.Event(), context.Event()
        first_queue, second_queue = context.Queue(), context.Queue()
        first = start(_writer, nodes / "leaf", item.name, payload, first_operation, first_queue,
                      before_replace=before_replace, resume=resume)
        assert before_replace.wait(PROCESS_TIMEOUT), "首个写入未到达替换前屏障"
        second = start(_writer, nodes / "leaf", item.name, payload, second_operation, second_queue,
                       attempted=second_attempt)
        assert second_attempt.wait(PROCESS_TIMEOUT), "第二个写入未尝试获取同一把锁"
        resume.set()
        results = [_result(first, first_queue), _result(second, second_queue)]

    assert all(result["ok"] for result in results), results
    state = _state(item)
    assert state["status"] == "in_progress"
    assert state["completed_at"] is None
    assert state["completed_at_unknown"] is False
    assert [record["id"] for record in state["activity_records"]] == [payload["id"]]


def test_lock_timeout_leaves_original_state_unchanged(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    item = _item(nodes, "leaf")
    state_path = item / ".state.json"
    before = state_path.read_bytes()
    payload = _payload(nodes, "leaf")
    with _children() as (context, start):
        results = context.Queue()
        with workflow._stable.state_lock(state_path):
            process = start(_writer, nodes / "leaf", item.name, payload, "activity", results,
                            lock_timeout=0.05)
            result = _result(process, results)

    assert result["ok"] is False, result
    assert result["value_error"] is True
    assert "锁" in result["message"]
    assert state_path.read_bytes() == before
    assert activity_closeout.append_activity(nodes / "leaf", item.name, payload)["status"] == "created"


def test_killing_lock_holder_releases_lock_without_manual_cleanup(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    item = _item(nodes, "leaf")
    state_path = item / ".state.json"
    before = state_path.read_bytes()
    with _children() as (context, start):
        acquired, release = context.Event(), context.Event()
        process = start(_holder, state_path, acquired, release)
        assert acquired.wait(PROCESS_TIMEOUT)
        process.kill()
        process.join(timeout=PROCESS_TIMEOUT)
        assert process.exitcode == -signal.SIGKILL

    assert state_path.read_bytes() == before
    result = activity_closeout.append_activity(
        nodes / "leaf", item.name, _payload(nodes, "leaf"), lock_timeout=0.2)
    assert result["status"] == "created"


def test_killing_writer_before_replace_preserves_original_and_allows_retry(tmp_path):
    nodes, _ = _copy_network(tmp_path)
    item = _item(nodes, "leaf")
    state_path = item / ".state.json"
    before = state_path.read_bytes()
    payload = _payload(nodes, "leaf")
    with _children() as (context, start):
        reached, resume, results = context.Event(), context.Event(), context.Queue()
        process = start(_writer, nodes / "leaf", item.name, payload, "activity", results,
                        before_replace=reached, resume=resume)
        assert reached.wait(PROCESS_TIMEOUT)
        assert state_path.read_bytes() == before
        process.kill()
        process.join(timeout=PROCESS_TIMEOUT)
        assert process.exitcode == -signal.SIGKILL

    assert state_path.read_bytes() == before
    assert activity_closeout.append_activity(nodes / "leaf", item.name, payload)["status"] == "created"
    assert activity_closeout.append_activity(nodes / "leaf", item.name, payload)["status"] == "unchanged"
    assert [record["id"] for record in _state(item)["activity_records"]] == [payload["id"]]


@pytest.mark.parametrize("failure", ["file_fsync", "replace"])
def test_failure_before_replace_preserves_bytes_and_retry_succeeds(tmp_path, monkeypatch, failure):
    nodes, _ = _copy_network(tmp_path)
    item = _item(nodes, "leaf")
    state_path = item / ".state.json"
    before = state_path.read_bytes()
    payload = _payload(nodes, "leaf")
    original_fsync = os.fsync

    def fail_file_fsync(descriptor):
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("测试注入：文件刷盘失败")
        original_fsync(descriptor)

    def fail_replace(source, destination):
        raise OSError("测试注入：替换失败")

    with monkeypatch.context() as patch:
        patch.setattr(workflow._stable.os, "fsync" if failure == "file_fsync" else "replace",
                      fail_file_fsync if failure == "file_fsync" else fail_replace)
        with pytest.raises(ValueError):
            activity_closeout.append_activity(nodes / "leaf", item.name, payload)
    assert state_path.read_bytes() == before
    assert not list(item.glob("*.tmp")), "正常捕获的写入失败应清理本次临时文件"
    assert activity_closeout.append_activity(nodes / "leaf", item.name, payload)["status"] == "created"
    assert len(_state(item)["activity_records"]) == 1


def test_directory_fsync_failure_reports_uncertain_result_and_retry_is_idempotent(tmp_path, monkeypatch):
    nodes, _ = _copy_network(tmp_path)
    item = _item(nodes, "leaf")
    payload = _payload(nodes, "leaf")
    original_fsync = os.fsync

    def fail_directory_fsync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("测试注入：目录刷盘失败")
        original_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(workflow._stable.os, "fsync", fail_directory_fsync)
        with pytest.raises(ValueError, match="结果待确认"):
            activity_closeout.append_activity(nodes / "leaf", item.name, payload)
    after_replace = (item / ".state.json").read_bytes()
    assert [record["id"] for record in _state(item)["activity_records"]] == [payload["id"]]
    assert activity_closeout.append_activity(nodes / "leaf", item.name, payload)["status"] == "unchanged"
    assert (item / ".state.json").read_bytes() == after_replace


def test_atomic_writer_uses_unique_temporary_files_and_flushes_before_replace(tmp_path, monkeypatch):
    path = tmp_path / ".state.json"
    stale = tmp_path / ".state.json.tmp"
    stale.write_bytes(b"old-unrelated-temporary-file")
    original_fsync, original_replace = os.fsync, os.replace
    events, temporary_paths = [], []
    expected = {}

    def observed_fsync(descriptor):
        metadata = os.fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode):
            assert json.loads(os.pread(descriptor, metadata.st_size, 0)) == expected
            events.append("file_fsync")
        else:
            assert stat.S_ISDIR(metadata.st_mode)
            events.append("directory_fsync")
        original_fsync(descriptor)

    def observed_replace(source, destination):
        source = Path(source)
        assert source.parent == path.parent
        assert source.suffix == ".tmp"
        assert source != stale
        assert Path(destination) == path
        temporary_paths.append(source)
        events.append("replace")
        original_replace(source, destination)

    monkeypatch.setattr(workflow._stable.os, "fsync", observed_fsync)
    monkeypatch.setattr(workflow._stable.os, "replace", observed_replace)
    for index in range(2):
        expected = {"id": index, "summary": "完整写入后再刷盘"}
        workflow._stable.write_json_atomic(path, expected)
        assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert events == ["file_fsync", "replace", "directory_fsync"] * 2
    assert len(set(temporary_paths)) == 2
    assert all(not temporary.exists() for temporary in temporary_paths)
    assert stale.read_bytes() == b"old-unrelated-temporary-file"
