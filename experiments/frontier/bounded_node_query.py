"""P4 有界查询入口：在独立进程内完成收集、来源复核和派生结果发布。"""

import json
import math
import multiprocessing
from pathlib import Path
import tempfile
import time


def _workflow():
    if __package__:
        from . import node_workflow
    else:
        import node_workflow
    return node_workflow


def _worker(request, output):
    workflow = _workflow()
    try:
        project = workflow.within(request["project"], request["source_root"])
        if request["scope"] == "self":
            node_id = workflow.identity(project)["node_id"]
            if node_id in request["denied"]:
                raise workflow.NodeError("本次请求明确拒绝读取")
            result = workflow.read_node(project)
        else:
            result = workflow.aggregate(project, request["source_root"], request["denied"],
                                        request["max_nodes"], request["max_depth"])
        result["query"] = {key: request[key] for key in ("scope", "max_nodes", "max_depth", "timeout_seconds", "max_bytes")}
        manifest = workflow.publish_run(result, request["source_root"], request["run_root"])
        manifest["query"] = result["query"]
        workflow.bounded(manifest, request["max_bytes"])
    except Exception as error:
        manifest = {"status": "failed", "error": str(error)}
        if len(workflow.encoded(manifest)) > request["max_bytes"]:
            manifest = {"status": "failed", "error": "查询失败，错误详情超过响应预算"}
    Path(output).write_bytes(workflow.encoded(manifest))


def query(project, source_root, scope="subtree", max_nodes=1000, max_depth=64,
          timeout_seconds=30.0, max_bytes=4096, denied=(), run_root=None):
    workflow = _workflow()
    if scope not in ("self", "subtree"):
        raise workflow.NodeError("范围必须为 self 或 subtree")
    if type(max_nodes) is not int or not 1 <= max_nodes <= 10000:
        raise workflow.NodeError("节点预算必须为 1 至 10000 的整数")
    if type(max_depth) is not int or not 0 <= max_depth <= 10000:
        raise workflow.NodeError("深度预算必须为 0 至 10000 的整数")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600:
        raise workflow.NodeError("时间预算必须为 0 至 3600 秒之间的有限正数")
    if type(max_bytes) is not int:
        raise workflow.NodeError("响应预算必须为整数")
    workflow.bounded({}, max_bytes)
    project = workflow.within(project, source_root)
    request = {"project": str(project), "source_root": str(Path(source_root).resolve()),
               "scope": scope, "max_nodes": max_nodes, "max_depth": max_depth,
               "timeout_seconds": timeout_seconds, "max_bytes": max_bytes,
               "denied": list(denied), "run_root": str(run_root) if run_root is not None else None}
    # 不跨进程比较 monotonic 起点；父进程独自计算截止时间并回收自己的只读工作者。
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="frontier-query-control-") as scratch:
        output = Path(scratch) / "manifest.json"
        process = multiprocessing.get_context("spawn").Process(target=_worker, args=(request, str(output)))
        process.start()
        try:
            process.join(max(0.0, timeout_seconds - (time.monotonic() - started)))
            if process.is_alive() or time.monotonic() - started >= timeout_seconds:
                return {"status": "failed", "error": "time_budget", "timeout_seconds": timeout_seconds}
            if process.exitcode != 0 or not output.is_file():
                raise workflow.NodeError("查询工作者异常退出，未返回可核验结果")
            raw = output.read_bytes()
            if len(raw) > max_bytes:
                raise workflow.NodeError("查询工作者响应超过预算，拒绝返回")
            result = json.loads(raw)
            return workflow.bounded(result, max_bytes)
        finally:
            if process.is_alive():
                process.kill()
                process.join(5)
            if process.is_alive():
                raise workflow.NodeError("查询超时且工作者回收失败，不能确认资源已释放")
            process.close()
