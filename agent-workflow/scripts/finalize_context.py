#!/usr/bin/env python3
"""开发任务结束时收口已发生的低风险事实。"""
from __future__ import annotations
import argparse, hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
import task_context

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def changed_files(project: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "status", "--short"], cwd=project, text=True, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line[3:].strip() for line in out.splitlines() if len(line) >= 4]

def update_current_status(item_path: Path, summary: str) -> None:
    status_path = item_path / "current-status.md"
    if not status_path.is_file():
        return
    text = status_path.read_text(encoding="utf-8")
    line = f"- 最近收口：{summary.strip()}"
    if "- 最近收口：" in text:
        text = "\n".join(line if item.startswith("- 最近收口：") else item for item in text.splitlines()) + "\n"
    else:
        text = text.rstrip() + f"\n\n## 自动收口摘要\n\n{line}\n"
    status_path.write_text(text, encoding="utf-8")


def finalize(project: Path, item_id: str, summary: str, tests: list[str] | None = None) -> dict[str, object]:
    if not summary.strip():
        raise ValueError("收口摘要不能为空")
    item = task_context.get_work_item(project, item_id)
    if not item:
        raise ValueError(f"找不到工作项：{item_id}")
    item_path = Path(item["path"])
    files = changed_files(project)
    payload = {"item": item_id, "summary": summary.strip(), "tests": tests or [], "files": files}
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    progress_dir = item_path / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    marker = progress_dir / f"finalize-{fingerprint}.md"
    if marker.exists():
        return {"recorded": False, "pending_confirmation": False, "path": str(marker)}
    target = progress_dir / f"finalize-{fingerprint}.md"
    target.write_text(f"# 开发收口\n\n- 时间：{now_iso()}\n- 摘要：{summary.strip()}\n- 实际变更：{', '.join(files) if files else '未检测到（可能未使用 Git）'}\n- 收口指纹：`{fingerprint}`\n", encoding="utf-8")
    update_current_status(item_path, summary)
    validation = item_path / "validation-log.md"
    with validation.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## 收口 {now_iso()}\n- 摘要：{summary.strip()}\n- 测试：{'; '.join(tests or []) or '未提供测试命令，未推断结果'}\n- 变更文件：{', '.join(files) if files else '未检测到'}\n")
    return {"recorded": True, "pending_confirmation": True, "path": str(target), "fingerprint": fingerprint}

def main() -> int:
    parser = argparse.ArgumentParser(description="收口开发事实")
    parser.add_argument("project", type=Path); parser.add_argument("item_id"); parser.add_argument("--summary", required=True); parser.add_argument("--test", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(finalize(args.project.resolve(), args.item_id, args.summary, args.test), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
