#!/usr/bin/env python3
"""生成、检查和发布独立的外部交付文档。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

DELIVERY_REL = Path(".agent-workflow") / "30-records" / "delivery"
STAGING = "staging"
PUBLISHED = "published"
ARCHIVE = "archive"
VALID_TYPES = {"weekly", "phase_report", "delivery", "acceptance", "release"}
VALID_STATUSES = {"draft", "review", "approved", "published", "superseded", "withdrawn", "archived"}
FORBIDDEN = (".agent-workflow/", "W-20", "待确认", "未验证", "可能")
SENSITIVE = re.compile(r"(?i)(password|passwd|token|secret|手机号|身份证)")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def delivery_root(project: Path) -> Path:
    return project / DELIVERY_REL


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_dirs(project: Path) -> None:
    for name in (STAGING, PUBLISHED, ARCHIVE):
        (delivery_root(project) / name).mkdir(parents=True, exist_ok=True)


def validate_metadata(metadata: dict[str, object], published: bool = False) -> None:
    required = {"artifact_id", "artifact_type", "audience", "period", "version", "status"}
    missing = sorted(required - metadata.keys())
    if missing:
        raise ValueError(f"交付物缺少字段：{'、'.join(missing)}")
    if metadata["artifact_type"] not in VALID_TYPES:
        raise ValueError("不支持的交付物类型")
    if not str(metadata["audience"]).strip() or not str(metadata["period"]).strip():
        raise ValueError("交付物必须填写 audience 和 period")
    if published and metadata["status"] != "published":
        raise ValueError("发布目录中的交付物必须是 published 状态")
    if metadata["status"] not in VALID_STATUSES:
        raise ValueError("不支持的交付物状态")


def check_content(content: str) -> list[str]:
    findings = []
    for marker in FORBIDDEN:
        if marker in content:
            findings.append(f"包含禁止内容：{marker}")
    if SENSITIVE.search(content):
        findings.append("可能包含敏感信息")
    return findings


def write_artifact(project: Path, artifact_id: str, artifact_type: str, audience: str, period: str, content: str,
                   source_paths: list[Path] | None = None) -> Path:
    if artifact_type not in VALID_TYPES:
        raise ValueError(f"不支持的交付物类型：{artifact_type}")
    findings = check_content(content)
    if findings:
        raise ValueError("；".join(findings))
    ensure_dirs(project)
    target = delivery_root(project) / STAGING / f"{artifact_id}.md"
    metadata = {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "audience": audience,
        "period": period,
        "version": 1,
        "status": "draft",
        "created_at": now_iso(),
    }
    target.write_text(content.rstrip() + "\n", encoding="utf-8")
    sources = []
    for source in source_paths or []:
        source = source.resolve()
        if not source.is_file():
            raise ValueError(f"找不到来源文件：{source}")
        sources.append({"path": str(source), "sha256": sha256(source), "captured_at": now_iso()})
    metadata["source_snapshot"] = {"content_sha256": sha256(target), "sources": sources, "captured_at": now_iso()}
    target.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def publish_artifact(project: Path, artifact_id: str) -> Path:
    ensure_dirs(project)
    source = delivery_root(project) / STAGING / f"{artifact_id}.md"
    metadata_path = source.with_suffix(".json")
    if not source.is_file() or not metadata_path.is_file():
        raise ValueError(f"找不到交付物草稿：{artifact_id}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    validate_metadata(metadata)
    findings = check_content(source.read_text(encoding="utf-8"))
    if findings:
        raise ValueError("；".join(findings))
    metadata.update({"status": "published", "approved_at": now_iso(), "published_at": now_iso(), "content_sha256": sha256(source)})
    metadata["provenance"] = {"artifact_id": artifact_id, "source_snapshot": metadata.get("source_snapshot", {}), "generated_at": metadata.get("created_at"), "published_at": metadata["published_at"]}
    target = delivery_root(project) / PUBLISHED / source.name
    if target.exists():
        raise ValueError("已发布版本不可原地覆盖")
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    target.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _artifact_paths(project: Path, artifact_id: str) -> tuple[Path, Path, str]:
    root = delivery_root(project)
    for directory in (PUBLISHED, STAGING, ARCHIVE):
        md = root / directory / f"{artifact_id}.md"
        if md.is_file():
            return md, md.with_suffix(".json"), directory
    raise ValueError(f"找不到交付物：{artifact_id}")


def _save_metadata(path: Path, metadata: dict[str, object]) -> None:
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def approve_artifact(project: Path, artifact_id: str) -> Path:
    md, meta_path, directory = _artifact_paths(project, artifact_id)
    if directory != STAGING:
        raise ValueError("只有 staging 草稿可以批准")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "draft":
        raise ValueError("只有 draft 状态可以批准")
    metadata.update({"status": "approved", "approved_at": now_iso()})
    _save_metadata(meta_path, metadata)
    return md


def _transition_published(project: Path, artifact_id: str, status: str, **extra: object) -> Path:
    md, meta_path, directory = _artifact_paths(project, artifact_id)
    if directory != PUBLISHED:
        raise ValueError("该操作只适用于 published 目录中的交付物")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "published":
        raise ValueError("只有 published 状态可以执行该操作")
    metadata.update({"status": status, **extra})
    _save_metadata(meta_path, metadata)
    return md


def supersede_artifact(project: Path, old_id: str, new_id: str) -> Path:
    if old_id == new_id:
        raise ValueError("新旧交付物不能相同")
    new_md, new_meta, directory = _artifact_paths(project, new_id)
    if directory != PUBLISHED:
        raise ValueError("替代版本必须先发布")
    metadata = json.loads(new_meta.read_text(encoding="utf-8"))
    if metadata.get("status") != "published":
        raise ValueError("替代版本必须处于 published 状态")
    old = _transition_published(project, old_id, "superseded", superseded_by=new_id, superseded_at=now_iso())
    metadata["supersedes"] = old_id
    _save_metadata(new_meta, metadata)
    return old


def withdraw_artifact(project: Path, artifact_id: str) -> Path:
    return _transition_published(project, artifact_id, "withdrawn", withdrawn_at=now_iso())


def archive_artifact(project: Path, artifact_id: str) -> Path:
    md, meta_path, directory = _artifact_paths(project, artifact_id)
    if directory not in (PUBLISHED, STAGING):
        raise ValueError("交付物已经归档")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if metadata.get("status") not in {"published", "withdrawn", "superseded", "draft", "approved"}:
        raise ValueError("当前状态不允许归档")
    metadata.update({"status": "archived", "archived_at": now_iso()})
    target = delivery_root(project) / ARCHIVE / md.name
    if target.exists():
        raise ValueError("归档目标已存在")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(md), str(target))
    shutil.move(str(meta_path), str(target.with_suffix(".json")))
    _save_metadata(target.with_suffix(".json"), metadata)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("artifact_id")
    generate.add_argument("artifact_type", choices=sorted(VALID_TYPES))
    generate.add_argument("--audience", required=True)
    generate.add_argument("--period", required=True)
    generate.add_argument("--content-file", required=True)
    publish = sub.add_parser("publish")
    publish.add_argument("artifact_id")
    approve = sub.add_parser("approve")
    approve.add_argument("artifact_id")
    supersede = sub.add_parser("supersede")
    supersede.add_argument("old_id")
    supersede.add_argument("new_id")
    withdraw = sub.add_parser("withdraw")
    withdraw.add_argument("artifact_id")
    archive = sub.add_parser("archive")
    archive.add_argument("artifact_id")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    try:
        if args.command == "generate":
            content = Path(args.content_file).read_text(encoding="utf-8")
            print(write_artifact(project, args.artifact_id, args.artifact_type, args.audience, args.period, content))
        elif args.command == "publish":
            print(publish_artifact(project, args.artifact_id))
        elif args.command == "approve":
            print(approve_artifact(project, args.artifact_id))
        elif args.command == "supersede":
            print(supersede_artifact(project, args.old_id, args.new_id))
        elif args.command == "withdraw":
            print(withdraw_artifact(project, args.artifact_id))
        else:
            print(archive_artifact(project, args.artifact_id))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"错误：{error}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
