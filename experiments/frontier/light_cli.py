"""轻量实验入口：接入项目、本地记录、按日期汇总、退出关联。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile

if __package__:
    from . import activity_closeout, light_report, node_workflow
    from .storage_common import RevisionConflict, mutated
else:
    import activity_closeout
    import light_report
    import node_workflow
    from storage_common import RevisionConflict, mutated


def connect(project, registry=None, parent=None, node_id=None):
    """显式接入 SQLite 关系；重复调用不清空数据库，不改变已有身份。"""
    project = Path(project).resolve()
    if not (project / ".agent-workflow").is_dir():
        raise ValueError("请先为项目准备原有 .agent-workflow 工作流")
    config_path = project / node_workflow.IDENTITY
    if config_path.is_symlink():
        raise ValueError("节点身份文件不能是符号链接")
    existing = node_workflow.identity(project) if config_path.exists() else None
    if (project / node_workflow.NODE_BACKUP).exists():
        raise ValueError("备份不能接入为活动节点")
    identifier = node_id.strip() if node_id is not None else (existing or {}).get("node_id", project.name)
    if not identifier:
        raise ValueError("节点身份不能为空")
    if existing and existing["node_id"] != identifier:
        raise ValueError("拒绝覆盖已有节点身份")
    if existing and existing.get("registry") and existing.get("backend", "file") != "sqlite":
        raise ValueError("已有节点使用非 SQLite 关系库，请先单独处理迁移；不会覆盖配置")
    parent_config = None
    if parent is not None:
        parent = Path(parent).resolve()
        parent_config = node_workflow.identity(parent)
        if (not parent_config.get("network_enabled") or not parent_config.get("registry") or
                parent_config.get("backend", "file") != "sqlite"):
            raise ValueError("上级节点尚未接入 SQLite 关系库")
    selected = registry or (parent_config or {}).get("registry") or (existing or {}).get("registry")
    if selected is None:
        raise ValueError("首次接入根节点需要 --registry；子节点可使用 --parent 继承关系库")
    if Path(selected).is_symlink():
        raise ValueError("关系库不能是符号链接")
    registry = Path(selected).resolve()
    for config in (existing, parent_config):
        if config and config.get("registry") and Path(config["registry"]).resolve() != registry:
            raise ValueError("现有节点或上级使用不同关系库，拒绝覆盖")
    if not registry.exists():
        if (existing and existing.get("registry")) or parent_config:
            raise ValueError("已配置的关系库不存在，拒绝创建空库替代")
        node_workflow.network_initialize(registry, "sqlite")
    parent_id = parent_config["node_id"] if parent_config else None
    store = node_workflow.registry_factory(registry, "sqlite")
    try:
        current = store.snapshot()
        node = {"id": identifier, "locator": str(project)}
        registered = next((value for value in current["nodes"] if value["id"] == identifier), None)
        if registered is not None and registered != node:
            raise ValueError("节点身份已在其他路径登记，请显式指定另一 --node-id")
        if any(value["locator"] == str(project) and value["id"] != identifier for value in current["nodes"]):
            raise ValueError("当前路径已使用另一节点身份登记")
        if parent_config and {"id": parent_id, "locator": str(parent)} not in current["nodes"]:
            raise ValueError("上级节点在关系库中尚未正确登记")
        edge = {"source": parent_id, "target": identifier, "kind": "contains"}
        additions = [edge] if parent_id and edge not in current["edges"] else []
        mutated(current, current["revision"], upsert_nodes=[node], add_edges=additions)
        if registered == node and not additions and existing and existing.get("network_enabled"):
            return {"status": "unchanged", "node_id": identifier, "registry_revision": current["revision"]}
    finally:
        store.close()
    node_workflow.initialize_node(project, identifier)
    node_workflow.enable(project, registry, "sqlite")
    for attempt in range(3):
        try:
            return node_workflow.join(project, parent_id)
        except RevisionConflict:
            if attempt == 2:
                raise ValueError("关系库正在被其他操作更新，请重试相同接入命令")


def record(project, item_id, activity_date, summary, status, evidence,
           line_start, line_end, activity_id=None):
    """仅写当前工作项；从参数创建活动和证据，不依赖节点关系。"""
    project = Path(project).resolve()
    try:
        normalized_date = date.fromisoformat(activity_date).isoformat()
    except (ValueError, TypeError) as error:
        raise ValueError("活动日期必须使用 YYYY-MM-DD 格式") from error
    if normalized_date != activity_date:
        raise ValueError("活动日期必须使用 YYYY-MM-DD 格式")
    relative = Path(evidence)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("证据必须是项目内相对路径，且不能包含 ..")
    if (not relative.parts or relative.parts[0] != ".agent-workflow" or
            relative.suffix not in (".md", ".json")):
        raise ValueError("证据必须是 .agent-workflow 内的 Markdown 或 JSON 文件")
    if relative.name == ".state.json":
        raise ValueError("请引用独立的进展或验证证据，不能把活动状态文件作为自身证据")
    ref = activity_closeout.evidence_ref(project, relative.as_posix(),
                                        line_start=line_start, line_end=line_end, hash_scope="lines")
    payload = {"date": normalized_date, "summary": summary.strip(), "status": status, "evidence_refs": [ref]}
    if activity_id is None:
        # ID 不随证据正文变化，重试时证据变更会被判为冲突，避免静默重复记账。
        identity = dict(payload, evidence_refs=[{key: value for key, value in ref.items() if key != "sha256"}])
        serialized = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        activity_id = "activity-" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
    payload["id"] = activity_id
    return activity_closeout.append_activity(project, item_id, payload)


def week_range(week, today=None):
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    if week == "last":
        monday -= timedelta(days=7)
    elif week != "this":
        raise ValueError("周范围必须是 this 或 last")
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    attach = commands.add_parser("connect", help="把当前项目接入 SQLite 节点关系")
    attach.add_argument("--project", type=Path, default=Path.cwd(), help="项目目录，默认当前目录")
    attach.add_argument("--registry", type=Path, help="SQLite 关系库；根节点首次接入必须指定")
    attach.add_argument("--parent", type=Path, help="已接入的上级项目目录，自动继承其关系库")
    attach.add_argument("--node-id", help="首次登记的节点身份，默认目录名；已有身份不可覆盖")
    local = commands.add_parser("record", help="只向当前工作项追加活动，无需接入网络")
    local.add_argument("--project", type=Path, default=Path.cwd(), help="项目目录，默认当前目录")
    local.add_argument("--item", required=True, help="已有工作项 ID")
    local.add_argument("--id", help="活动唯一 ID；省略时根据规范化内容生成，重试不重复")
    local.add_argument("--date", required=True, help="实际活动日期 YYYY-MM-DD，不从日志推断")
    local.add_argument("--summary", required=True, help="本次活动的事实摘要")
    local.add_argument("--status", required=True, choices=sorted(activity_closeout.ACTIVITY_STATUSES), help="本次活动状态，不更改工作项生命周期")
    local.add_argument("--evidence", required=True, help=".agent-workflow 内证据文件的项目相对路径")
    local.add_argument("--line-start", required=True, type=int, help="证据起始行，包含该行")
    local.add_argument("--line-end", required=True, type=int, help="证据结束行，包含该行")
    report = commands.add_parser("report", help="按起止日期只读汇总当前节点及下级活动")
    report.add_argument("--project", type=Path, default=Path.cwd(), help="发起汇总的节点目录")
    report.add_argument("--source-root", required=True, type=Path, help="本次授权读取的项目共同根目录")
    report.add_argument("--start", help="开始日期 YYYY-MM-DD，包含当天；与 --end 同用")
    report.add_argument("--end", help="结束日期 YYYY-MM-DD，包含当天")
    report.add_argument("--week", choices=("this", "last"), help="本周/上周，按本机日期计算周一至周日；不与起止日期混用")
    report.add_argument("--scope", choices=("self", "subtree"), default="subtree", help="self 仅当前项目且无需接入关系库；默认 subtree 包含下级")
    report.add_argument("--deny", action="append", default=[], help="拒绝读取的节点身份，可重复")
    report.add_argument("--max-nodes", type=int, default=100, help="最多读取的节点数，默认 100，其他节点显示为缺口")
    report.add_argument("--max-depth", type=int, default=10, help="最多读取的层数，默认 10，当前节点为第 0 层")
    destination = report.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path, help="报告文件，必须位于来源根目录之外；默认输出到终端")
    destination.add_argument("--save", action="store_true", help="自动保存到独立临时报告目录，仅输出路径和覆盖统计，避免加载全文")
    detach = commands.add_parser("leave", help="退出关联，保留单节点工作流和活动")
    detach.add_argument("--project", type=Path, default=Path.cwd(), help="项目目录，默认当前目录")
    args = parser.parse_args(argv)
    try:
        if args.command == "connect":
            result = connect(args.project, args.registry, args.parent, args.node_id)
            sys.stdout.write("项目已接入：{}（{}）\n".format(result["node_id"], result["status"]))
        elif args.command == "record":
            result = record(args.project, args.item, args.date, args.summary, args.status,
                            args.evidence, args.line_start, args.line_end, args.id)
            sys.stdout.write("本地活动已记录：{}（{}）\n".format(result["record"]["id"], result["status"]))
        elif args.command == "leave":
            result = node_workflow.leave(args.project)
            sys.stdout.write("项目已退出关联，本地工作流保留：{}（{}）\n".format(result["node_id"], result["status"]))
            if result["status"] == "partial":
                sys.stderr.write("关系清理尚未完成，可重试前先核查关系库：{}\n".format(result.get("error", "未知原因")))
                return 2
        else:
            if args.week:
                if args.start or args.end:
                    raise ValueError("--week 不能与 --start/--end 同用")
                args.start, args.end = week_range(args.week)
            if not args.start or not args.end:
                raise ValueError("请提供 --week 或完整的 --start/--end")
            if args.save:
                light_report._outside(Path(tempfile.gettempdir()) / "frontier-report", args.source_root)
            if args.output is not None:
                light_report._outside(args.output, args.source_root)
            result, report = light_report.generate(args.project, args.source_root, args.deny,
                                                  args.start, args.end, args.max_nodes, args.max_depth, args.scope)
            if args.save:
                args.output = Path(tempfile.mkdtemp(prefix="agent-workflow-report-")) / "report.md"
            if args.output is None:
                sys.stdout.write(report)
            else:
                destination = light_report._outside(args.output, args.source_root, result.get("_registry"))
                light_report.write_report(report, destination)
                sys.stdout.write("报告已写入：{}\n".format(args.output.resolve()))
                coverage = result["coverage"]
                sys.stdout.write("范围：{} 至 {}；节点读取：{}；成功 {}，失败 {}，跳过 {}。日期缺口请查看报告。\n".format(
                    args.start, args.end, result["status"], len(coverage["succeeded"]),
                    len(coverage["failed"]), len(coverage["skipped"])))
            return 0 if result["status"] == "full" else 2
        return 0
    except Exception as error:
        sys.stderr.write("操作失败：{}\n".format(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
