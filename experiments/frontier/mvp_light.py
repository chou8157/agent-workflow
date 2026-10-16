"""轻量 MVP：把确定性聚合结果渲染为可读报告，不改变事实来源。"""

from __future__ import annotations

from collections import Counter
from datetime import date


CLAIM_FIELDS = {"title", "status", "completed_at", "completed_at_status"}
AGENT_DRAFT_FIELDS = frozenset(("sections", "omitted"))
AGENT_SECTION_FIELDS = frozenset(("fact_refs", "claims", "text"))
AGENT_CLAIM_FIELDS = frozenset(("fact_ref", "field", "value"))


def summarize(result):
    """只使用程序已校验的 facts/coverage，生成稳定的报告数据。"""
    facts = sorted(result.get("facts", []), key=lambda item: (
        item["origin_node_id"], item["work_item_id"]))
    coverage = result.get("coverage", {})
    return {
        "status": result["status"],
        "registry_revision": result.get("registry_revision"),
        "coverage": {
            "expected": list(coverage.get("expected", [])),
            "visited": list(coverage.get("visited", [])),
            "succeeded": list(coverage.get("succeeded", [])),
            "failed": dict(sorted(coverage.get("failed", {}).items())),
            "skipped": dict(sorted(coverage.get("skipped", {}).items())),
        },
        "facts": [
            {
                "node_id": fact["origin_node_id"],
                "work_item_id": fact["work_item_id"],
                "title": fact["title"],
                "status": fact["status"],
                "completed_at": fact["completed_at"],
                "completed_at_status": fact["completed_at_status"],
                "activity_records": [
                    {
                        "id": activity["id"],
                        "date": activity["date"],
                        "summary": activity["summary"],
                        "status": activity["status"],
                        "source_path": activity["source"]["path"],
                        "source_sha256": activity["source"]["sha256"],
                    }
                    for activity in fact.get("activity_records", [])
                ],
                "source_hashes": sorted({source["sha256"] for source in fact["sources"]}),
            }
            for fact in facts
        ],
    }


def render_markdown(result):
    """渲染可读摘要；没有日期时明确写未知，不用文件时间补造。"""
    data = summarize(result)
    coverage = data["coverage"]
    lines = [
        "# 多项目工作摘要",
        "",
        "- 聚合状态：{}".format(data["status"]),
        "- 关系版本：{}".format(data["registry_revision"]),
        "- 计划覆盖：{} 个节点；成功读取：{} 个；缺口：{} 个".format(
            len(coverage["expected"]), len(coverage["succeeded"]),
            len(coverage["failed"]) + len(coverage["skipped"])),
        "",
        "## 已读取事实",
    ]
    if not data["facts"]:
        lines.append("- 无已核验事实")
    for fact in data["facts"]:
        date = fact["completed_at"] if fact["completed_at_status"] == "known" else "未记录日期"
        lines.append("- [{}] {}：{}（完成日期：{}）".format(
            fact["node_id"], fact["title"], fact["status"], date))
        for activity in fact["activity_records"]:
            lines.append("  - 活动 {}：{}（{}，来源：{}）".format(
                activity["date"], activity["summary"], activity["status"], activity["source_path"]))
    lines.extend(["", "## 未覆盖或失败"])
    gaps = list(coverage["failed"].items()) + list(coverage["skipped"].items())
    if not gaps:
        lines.append("- 无")
    else:
        for node_id, reason in sorted(gaps):
            lines.append("- [{}] {}".format(node_id, reason))
    lines.extend(["", "## 事实口径", "- 以上内容只来自节点工作流文件；未记录日期的事实不参与时间范围推断。"])
    return "\n".join(lines) + "\n"


def extract_activity_records(result):
    """只读取工作项 state 中的结构化活动；忽略日志和状态文档中的普通日期。"""
    records = []
    for fact in result.get("facts", []):
        for activity in fact.get("activity_records", []):
            source = activity["source"]
            records.append({
                "node_id": fact["origin_node_id"],
                "work_item_id": fact["work_item_id"],
                "activity_id": activity["id"],
                "date": activity["date"],
                "summary": activity["summary"],
                "status": activity["status"],
                "evidence_refs": activity.get("evidence_refs", []),
                "source_path": source["path"],
                "source_sha256": source["sha256"],
                "line_start": source["line_start"],
                "line_end": source["line_end"],
            })
    return sorted(records, key=lambda item: (
        item["date"], item["node_id"], item["work_item_id"], item["activity_id"]))


def activity_window(result, start_date, end_date):
    """返回日期窗口内的记录，并区分未知日期与窗口外的已记录节点。"""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError) as error:
        raise ValueError("活动日期必须使用 YYYY-MM-DD 格式") from error
    if start.isoformat() != start_date or end.isoformat() != end_date:
        raise ValueError("活动日期必须使用 YYYY-MM-DD 格式")
    if start > end:
        raise ValueError("活动日期范围无效")
    records = extract_activity_records(result)
    expected = set(result.get("coverage", {}).get("succeeded", []))
    recorded = {record["node_id"] for record in records}
    expected_work_items = {
        "{}/{}".format(fact["origin_node_id"], fact["work_item_id"])
        for fact in result.get("facts", [])
    }
    recorded_work_items = {"{}/{}".format(record["node_id"], record["work_item_id"])
                           for record in records}
    selected = [record for record in records
                if start <= date.fromisoformat(record["date"]) <= end]
    selected_nodes = {record["node_id"] for record in selected}
    selected_work_items = {"{}/{}".format(record["node_id"], record["work_item_id"])
                           for record in selected}
    unknown_date_work_items = sorted(expected_work_items - recorded_work_items)
    recorded_outside_window_work_items = sorted(recorded_work_items - selected_work_items)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "records": selected,
        "unknown_date_nodes": sorted(expected - recorded),
        "recorded_outside_window_nodes": sorted(recorded - selected_nodes),
        "unknown_date_work_items": unknown_date_work_items,
        "recorded_outside_window_work_items": recorded_outside_window_work_items,
    }


def render_activity_window(result, start_date, end_date):
    """渲染日期窗口；窗口外或无日期只作为缺口提示，不声称没有工作。"""
    window = activity_window(result, start_date, end_date)
    coverage = result.get("coverage", {})
    lines = [
        "# 记录活动摘要",
        "",
        "- 查询范围：{} 至 {}（包含起止日）".format(start_date, end_date),
        "- 节点读取状态：{}；关系版本：{}".format(result["status"], result.get("registry_revision")),
        "- 计划覆盖：{} 个节点；成功读取：{} 个；失败：{} 个；跳过：{} 个".format(
            len(coverage.get("expected", [])), len(coverage.get("succeeded", [])),
            len(coverage.get("failed", {})), len(coverage.get("skipped", {}))),
        "- 事实来源：工作项 .state.json 中的结构化 activity_records",
        "",
        "## 窗口内记录",
    ]
    if not window["records"]:
        lines.append("- 未发现窗口内的显式日期记录")
    else:
        for record in window["records"]:
            lines.append("- [{}] {}：{}（{}，来源：{}:{}-{}）".format(
                record["node_id"], record["date"], record["summary"], record["status"],
                record["source_path"], record["line_start"], record["line_end"]))
            lines.append("  - 工作项：{}；活动：{}；来源 SHA-256：{}".format(
                record["work_item_id"], record["activity_id"], record["source_sha256"]))
            for ref in record["evidence_refs"]:
                lines.append("  - 证据：{}:{}-{}；SHA-256：{}；哈希范围：{}".format(
                    ref["path"], ref["line_start"], ref["line_end"], ref["sha256"],
                    ref.get("hash_scope", "file")))
    lines.extend(["", "## 未覆盖或失败"])
    gaps = list(coverage.get("failed", {}).items()) + list(coverage.get("skipped", {}).items())
    if not gaps:
        lines.append("- 无节点读取缺口")
    for node_id, reason in sorted(gaps):
        lines.append("- [{}] {}".format(node_id, reason))
        for detail in result.get("gaps", {}).get(node_id, []):
            lines.append("  - {}".format(detail))
    lines.extend(["", "## 日期记录缺口（unknown_date）"])
    unknown_nodes_with_items = {work_item.split("/", 1)[0] for work_item in window["unknown_date_work_items"]}
    for node_id in window["unknown_date_nodes"]:
        if node_id not in unknown_nodes_with_items:
            lines.append("- [{}] 没有可识别的日期记录，不能判断该范围内是否有工作".format(node_id))
    for work_item in window["unknown_date_work_items"]:
        node_id, item_id = work_item.split("/", 1)
        lines.append("- [{}] 工作项 {} 没有可识别的日期记录，不能判断该范围内是否有工作".format(node_id, item_id))
    for work_item in window["recorded_outside_window_work_items"]:
        node_id, item_id = work_item.split("/", 1)
        lines.append("- [{}] 工作项 {} 有日期记录，但不在本次范围内；不能据此断言没有其他未记录工作".format(node_id, item_id))
    if not (window["unknown_date_nodes"] or window["unknown_date_work_items"] or
            window["recorded_outside_window_work_items"]):
        lines.append("- 未发现缺少日期记录的已读工作项")
    lines.extend(["", "## 事实口径", "- 节点读取完整不代表活动历史完整；只汇总已显式记录的活动，不从日志日期或文件时间推断工作。"])
    return "\n".join(lines) + "\n"


def status_counts(result):
    """为测试和调用方提供简单状态计数。"""
    return Counter(fact["status"] for fact in result.get("facts", []))


def fact_key(fact):
    return "{}/{}".format(fact["node_id"], fact["work_item_id"])


def index_agent_facts(summary):
    """拒绝身份冲突，保证校验和展示使用同一份事实。"""
    facts = {}
    for fact in summary.get("facts", []):
        ref = fact_key(fact)
        if ref in facts:
            raise ValueError("事实包重复引用：{}".format(ref))
        facts[ref] = fact
    return facts


def validate_agent_draft(summary, draft):
    """校验 Agent 的引用和结构化声明；自然语言只作为非权威表达。"""
    facts = index_agent_facts(summary)
    known = set(facts)
    sections = draft.get("sections") if isinstance(draft, dict) else None
    omitted = draft.get("omitted", []) if isinstance(draft, dict) else []
    if not isinstance(sections, list) or not isinstance(omitted, list):
        raise ValueError("Agent 草稿必须包含 sections 和 omitted 列表")
    if set(draft) != AGENT_DRAFT_FIELDS:
        raise ValueError("Agent 草稿缺少必需字段或包含未定义字段")
    covered = []
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("text"), str) or not section["text"].strip():
            raise ValueError("Agent 草稿段落缺少可读文本")
        if set(section) != AGENT_SECTION_FIELDS:
            raise ValueError("Agent 草稿段落缺少必需字段或包含未定义字段")
        refs = section.get("fact_refs")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("Agent 草稿段落必须提供 fact_refs")
        covered.extend(refs)
        claims = section.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError("Agent 草稿段落必须提供 claims")
        claim_refs = []
        claim_keys = set()
        for claim in claims:
            if not isinstance(claim, dict):
                raise ValueError("Agent 事实声明必须是对象")
            if set(claim) != AGENT_CLAIM_FIELDS:
                raise ValueError("Agent 事实声明缺少必需字段或包含未定义字段")
            ref = claim.get("fact_ref")
            field = claim.get("field")
            if not isinstance(ref, str) or ref not in known:
                raise ValueError("Agent 事实声明引用未知事实：{}".format(ref))
            if not isinstance(field, str) or field not in CLAIM_FIELDS:
                raise ValueError("Agent 事实声明字段不允许：{}".format(field))
            if (ref, field) in claim_keys:
                raise ValueError("Agent 重复声明字段：{} {}".format(ref, field))
            claim_keys.add((ref, field))
            expected = facts[ref][field]
            if type(claim["value"]) is not type(expected) or claim["value"] != expected:
                raise ValueError("Agent 事实声明与来源不一致：{} {}".format(ref, field))
            claim_refs.append(ref)
        if set(refs) != set(claim_refs):
            raise ValueError("Agent fact_refs 与 claims 覆盖范围不一致")
    if len(covered) != len(set(covered)):
        raise ValueError("Agent 草稿重复引用事实")
    unknown = sorted(set(covered) - known)
    if unknown:
        raise ValueError("Agent 草稿引用未知事实：{}".format(", ".join(unknown)))
    if any(not isinstance(ref, str) for ref in omitted):
        raise ValueError("Agent 草稿 omitted 必须是事实引用列表")
    if len(omitted) != len(set(omitted)):
        raise ValueError("Agent 草稿重复省略事实")
    if set(omitted) - known:
        raise ValueError("Agent 草稿 omitted 引用未知事实")
    if set(covered) & set(omitted):
        raise ValueError("Agent 草稿不能同时覆盖和省略同一事实")
    unresolved = sorted(known - set(covered) - set(omitted))
    if unresolved:
        raise ValueError("Agent 草稿未说明事实是否省略：{}".format(", ".join(unresolved)))
    return {"sections": sections, "covered": sorted(covered), "omitted": sorted(omitted)}
