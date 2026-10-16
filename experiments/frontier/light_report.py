"""轻量多节点只读报告入口。

该入口只读取节点工作流并生成派生 Markdown，不向任何节点写回内容。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

if __package__:
    from . import mvp_light, node_workflow
else:
    import mvp_light
    import node_workflow


def _outside(path, source_root, registry=None):
    path = Path(path).resolve()
    source_root = Path(source_root).resolve()
    if path == source_root or source_root in path.parents:
        raise ValueError("派生报告必须写在授权来源目录之外")
    if registry and registry.get("backend") == "sqlite":
        database = Path(registry["locator"]).resolve()
        protected = {database, Path(str(database) + "-wal"), Path(str(database) + "-shm"),
                     Path(str(database) + "-journal")}
        if path in protected:
            raise ValueError("派生报告不能覆盖关系库或其持久化辅助文件")
    return path


def write_report(report, destination):
    """原子写入派生报告，避免留下半份结果。"""
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(report)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(destination))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def generate(project, source_root, denied=(), start_date=None, end_date=None,
             max_nodes=None, max_depth=None, scope="subtree"):
    """读取固定范围并渲染报告；事实读取和缺口判断由确定性适配器负责。"""
    if (start_date is None) != (end_date is None):
        raise ValueError("必须同时提供开始日期和结束日期")
    if start_date is not None:
        mvp_light.activity_window({"facts": []}, start_date, end_date)
    if scope == "self":
        project = node_workflow.within(project, source_root)
        config = None
        try:
            if (project / node_workflow.IDENTITY).exists():
                config = node_workflow.identity(project)
        except (OSError, ValueError) as error:
            if denied:
                raise ValueError("节点身份无法读取，不能可靠核对本次拒绝列表") from error
        local_id = config["node_id"] if config else project.name
        if local_id in denied or project.name in denied:
            raise ValueError("本次请求明确拒绝读取当前项目")
        result = node_workflow.read_node(project, expected_node_id=local_id, standalone=True)
        node_id = result["origin_node_id"]
        result["coverage"] = {"expected": [node_id], "visited": [node_id],
                              "succeeded": [node_id] if result["status"] == "full" else [],
                              "failed": {} if result["status"] == "full" else {node_id: "原始工作项文档缺失或损坏"},
                              "skipped": {}}
        result["gaps"] = {node_id: result["gaps"]} if result["gaps"] else {}
        # 本地报告不连接关系库；仅保留已知库路径以防输出文件覆盖它。
        if config and config.get("registry"):
            result["_registry"] = {"backend": config.get("backend"), "locator": config["registry"]}
    elif scope == "subtree":
        result = node_workflow.aggregate(project, source_root, denied=denied,
                                         max_nodes=max_nodes, max_depth=max_depth)
    else:
        raise ValueError("报告范围必须是 self 或 subtree")
    if start_date is None:
        return result, mvp_light.render_markdown(result)
    return result, mvp_light.render_activity_window(result, start_date, end_date)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path, help="发起汇总的节点目录")
    parser.add_argument("--source-root", required=True, type=Path, help="本次允许读取的来源根目录")
    parser.add_argument("--deny", action="append", default=[], help="明确拒绝读取的节点，可重复")
    parser.add_argument("--output", type=Path, help="派生 Markdown 输出路径，必须在来源根之外")
    parser.add_argument("--start", help="活动开始日期，YYYY-MM-DD，包含当天；与 --end 同用")
    parser.add_argument("--end", help="活动结束日期，YYYY-MM-DD，包含当天")
    parser.add_argument("--max-nodes", type=int, help="本次最多读取的节点数，超出部分显示为缺口")
    parser.add_argument("--max-depth", type=int, help="本次最多读取的层数，当前节点为第 0 层")
    args = parser.parse_args(argv)
    try:
        if args.output is not None:
            _outside(args.output, args.source_root)
        result, report = generate(args.project, args.source_root, args.deny,
                                  args.start, args.end, args.max_nodes, args.max_depth)
        if args.output is None:
            sys.stdout.write(report)
        else:
            destination = _outside(args.output, args.source_root, result.get("_registry"))
            write_report(report, destination)
            sys.stdout.write("报告已写入：{}\n".format(destination))
        return 0 if result["status"] == "full" else 2
    except Exception as error:
        sys.stderr.write("报告生成失败：{}\n".format(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
