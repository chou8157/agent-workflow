"""只读分析现有工作记录，生成 activity_records 迁移候选，不写回项目。"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import stat

if __package__:
    from . import node_workflow
    from .coordinator import _read_bytes, SourceReadError
else:
    import node_workflow
    from coordinator import _read_bytes, SourceReadError


DATE_HEADING = re.compile(r"^\s*#{1,6}\s+(20\d{2}-\d{2}-\d{2})(?:\s+.*|[-：:].*)?$")
DATE_LABEL = re.compile(r"^\s*-?\s*日期[：:]\s*(20\d{2}-\d{2}-\d{2})\s*$")
ISO_DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
WORK_ITEMS = Path(".agent-workflow/30-records/work-items")
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * MAX_FILE_BYTES
MAX_FILES = 1000
MAX_DIRECTORY_ENTRIES = 2000
MAX_DATE_LOCATIONS = 2000
MAX_ISSUES = 200


def _issue(scan, issues, value):
    """限制诊断数量，避免异常目录把 dry-run 输出本身撑爆。"""
    if len(issues) < MAX_ISSUES:
        issues.append(value)
    elif len(issues) == MAX_ISSUES:
        issues.append({"source": ".", "kind": "budget", "reason": "诊断数量超过输出预算，后续问题已合并"})


class Scan:
    """限定扫描范围和资源；仅返回位置、哈希与诊断，不返回项目正文。"""

    def __init__(self, project):
        self.project = project
        self.files_attempted = 0
        self.bytes_read = 0
        self.date_locations = 0
        self.sources = []

    def check_directory(self, path):
        current = self.project
        for part in path.relative_to(self.project).parts:
            current = current / part
            if not stat.S_ISDIR(current.lstat().st_mode):
                raise ValueError("目录不是普通目录或包含符号链接")

    def entries(self, path, issues, optional=False):
        if len(issues) >= MAX_ISSUES:
            return []
        discovered = False
        try:
            self.check_directory(path)
            discovered = True
            entries = []
            with os.scandir(path) as iterator:
                for entry in iterator:
                    if len(entries) == MAX_DIRECTORY_ENTRIES:
                        raise ValueError("目录条目超过盘点预算，请缩小范围")
                    entries.append(Path(entry.path))
            return sorted(entries)
        except FileNotFoundError:
            if not optional or discovered:
                _issue(self, issues, {"source": str(path.relative_to(self.project)), "kind": "missing", "reason": "目录缺失"})
        except (OSError, ValueError) as error:
            _issue(self, issues, {"source": str(path.relative_to(self.project)), "kind": "unreadable", "reason": str(error)})
        return []

    def read(self, path, issues, required=False):
        if len(issues) >= MAX_ISSUES:
            return None
        relative = str(path.relative_to(self.project))
        discovered = False
        try:
            self.check_directory(path.parent)
            metadata = path.lstat()
            discovered = True
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("来源不是普通文件或为符号链接")
            remaining = MAX_TOTAL_BYTES - self.bytes_read
            if self.files_attempted >= MAX_FILES or remaining <= 0 or metadata.st_size > min(MAX_FILE_BYTES, remaining - 1):
                raise ValueError("来源超过盘点读取预算，请缩小范围")
            self.files_attempted += 1
            # 留出一个探测字节，即使来源并发增长也不会超过本轮总预算。
            raw = _read_bytes(path, max_bytes=min(MAX_FILE_BYTES, remaining - 1))
            self.bytes_read += len(raw)
            source = {"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            self.sources.append(source)
            return {"content": raw.decode("utf-8"), "source": source}
        except FileNotFoundError:
            if required or discovered:
                _issue(self, issues, {"source": relative, "kind": "missing", "reason": "已发现文件在读取时消失" if discovered else "文件缺失"})
        except (OSError, ValueError, UnicodeError) as error:
            if isinstance(error, SourceReadError):
                self.bytes_read += error.bytes_read
            _issue(self, issues, {"source": relative, "kind": "unreadable", "reason": str(error)})
        return None


def _valid_date(value):
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def _dates(content):
    """提取记录日期和行号；不把它们直接转换成活动事实。"""
    lines = content.splitlines()
    fence = None
    for number, line in enumerate(lines, 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        date_line = number
        match = DATE_HEADING.match(line) or DATE_LABEL.match(line)
        if match is None and line.strip() in {"## 日期", "日期"}:
            for offset, following in enumerate(lines[number:number + 3], 1):
                if following.strip():
                    if ISO_DATE.fullmatch(following.strip()):
                        match = ISO_DATE.fullmatch(following.strip())
                        date_line = number + offset
                    break
        if match is None:
            continue
        value = match.group(1) if match.lastindex else match.group(0)
        if _valid_date(value):
            yield {"date": value, "line": date_line}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 包含重复字段：{}".format(key))
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("JSON 包含非标准数值：{}".format(value))


def scan_work_item(item, scan=None):
    item = Path(item)
    if scan is None:
        item = item.absolute()
        scan = Scan(item.parent)
    result = {
        "work_item_id": item.name,
        "state": "unknown",
        "activity_record_count": 0,
        "candidate_record_dates": [],
        "ignored_status_dates": [],
        "missing_documents": [],
        "invalid_state": None,
        "state_format": "unknown",
        "issues": [],
    }
    issues = result["issues"]
    try:
        scan.check_directory(item)
    except (OSError, ValueError) as error:
        _issue(scan, issues, {"source": item.name, "kind": "unreadable", "reason": str(error)})
        return result
    state_path = item / ".state.json"
    state_document = scan.read(state_path, issues, required=True)
    if state_document is not None:
        try:
            state = json.loads(state_document["content"], object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if not isinstance(state, dict):
                raise ValueError("状态文件必须是 JSON 对象")
            node_workflow._stable.validate_state(state, item.name)
            records = node_workflow.activity_records(state, item.name, state_document)
            result["activity_record_count"] = len(records)
            result["state"] = state["status"]
            result["state_format"] = "structured"
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            result["invalid_state"] = str(error)
            result["state_format"] = "invalid"
    else:
        result["state_format"] = "unavailable"
    documents = {}
    for name in ("work-item.md", "current-status.md"):
        documents[name] = scan.read(item / name, issues, required=True)
    paths = [(item / "validation-log.md", "validation_record")]
    paths += [(path, "progress_record") for path in scan.entries(item / "progress", issues, optional=True) if path.suffix == ".md"]
    paths += [(item / "current-status.md", "status_document")]
    for path, kind in paths:
        document = documents.get(path.name) if kind == "status_document" else scan.read(path, issues, required=kind == "progress_record")
        if document is None:
            continue
        for found in _dates(document["content"]):
            if scan.date_locations >= MAX_DATE_LOCATIONS:
                _issue(scan, issues, {"source": str(path.relative_to(item)), "kind": "budget", "reason": "日期位置超过输出预算，结果不完整"})
                break
            scan.date_locations += 1
            location = dict(found, source=str(path.relative_to(item)), source_sha256=document["source"]["sha256"], kind=kind)
            if kind == "status_document":
                location["reason"] = "状态文档日期不自动视为业务活动"
                result["ignored_status_dates"].append(location)
            else:
                location["requires_confirmation"] = True
                result["candidate_record_dates"].append(location)
    result["missing_documents"] = [Path(issue["source"]).name for issue in issues if issue["kind"] == "missing"]
    if ".state.json" in result["missing_documents"] and all(documents.values()):
        result["state_format"] = "legacy_unmigrated_candidate"
    return result


def scan_project(project):
    project = Path(project).resolve()
    scan, issues = Scan(project), []
    root = project / WORK_ITEMS
    items = [path for path in scan.entries(root, issues) if path.name.startswith("W-")]
    work_items = [scan_work_item(item, scan) for item in items]
    candidates = [candidate for item in work_items for candidate in item["candidate_record_dates"]]
    return {
        "project": str(project),
        "status": "failed" if issues else ("partial" if any(item["issues"] or item["invalid_state"] for item in work_items) else "full"),
        "coverage": "工作项必需文档可读性、状态格式和有限范围的显式记录日期；不是业务活动完整性验收",
        "issues": issues,
        "work_item_count": len(work_items),
        "activity_record_count": sum(item["activity_record_count"] for item in work_items),
        "work_items_with_activity_records": sum(item["activity_record_count"] > 0 for item in work_items),
        "work_items_without_confirmed_activity_records": [item["work_item_id"] for item in work_items if not item["activity_record_count"]],
        "candidate_record_date_count": len(candidates),
        "candidate_record_dates": sorted({candidate["date"] for candidate in candidates}),
        "candidate_requires_confirmation": bool(candidates),
        "sources": scan.sources,
        "read_metrics": {"files_attempted": scan.files_attempted, "bytes_read": scan.bytes_read},
        "limits": {"file_bytes": MAX_FILE_BYTES, "total_bytes": MAX_TOTAL_BYTES, "files": MAX_FILES,
                   "directory_entries": MAX_DIRECTORY_ENTRIES, "date_locations": MAX_DATE_LOCATIONS,
                   "issues": MAX_ISSUES},
        "work_items": work_items,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="项目根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    result = scan_project(args.project)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("项目：{}".format(result["project"]))
        print("状态：{}；工作项：{}；已有活动记录：{}；候选记录日期：{}".format(
            result.get("status"), result.get("work_item_count", 0),
            result.get("activity_record_count", 0), result.get("candidate_record_date_count", 0)))
        if result.get("candidate_requires_confirmation"):
            print("候选日期只供人工确认，不会自动写入 activity_records。")
    return 0 if result.get("status") == "full" else 2


if __name__ == "__main__":
    raise SystemExit(main())
