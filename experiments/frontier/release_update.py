"""技能程序连续更新：本机备份、内容绑定、互斥切换和中断恢复。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
import uuid

if __package__:
    from . import build_release as release
elif Path(__file__).with_name("release_package.py").is_file():
    import release_package as release
else:
    import build_release as release


CONTROL = ".agent-workflow-updates"
LOCK = ".agent-workflow-update.lock"
FINAL_STATES = {"committed", "recovered"}


def _safe_path(value):
    path = Path(value).expanduser().absolute()
    for part in (path,) + tuple(path.parents):
        if part.is_symlink():
            raise ValueError("更新路径不能经过符号链接：{}".format(part))
    return path.resolve()


def _sync(directory):
    descriptor = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(release._canonical(data))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _sync(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sync_tree(root):
    for parent, directories, files in os.walk(root, topdown=False):
        for filename in files:
            descriptor = os.open(str(Path(parent) / filename), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        _sync(parent)


def _snapshot(path):
    path = _safe_path(path)
    if not path.is_dir():
        raise ValueError("技能目录不存在：{}；首次使用请执行 install".format(path))
    files, directories = release._inventory(path)
    release._skill_name(path / "SKILL.md")
    manifest_path = path / release.MANIFEST
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest = release.verify(path)
        kind, version = "manifest", manifest["version"]
    else:
        kind, version = "legacy-untracked", None
    if manifest_path.exists():
        raw = manifest_path.read_bytes()
        files[release.MANIFEST] = {"sha256": release._digest(raw), "size": len(raw)}
    modes = {name: stat.S_IMODE((path / name).stat().st_mode) for name in list(files) + directories}
    fingerprint = release._digest(release._canonical({"files": files, "directories": directories,
                                                      "modes": modes, "root_mode": stat.S_IMODE(path.stat().st_mode)}))
    return {"kind": kind, "version": version, "fingerprint": fingerprint, "files": len(files)}


@contextmanager
def installation_lock(skills_root, create=False, timeout=5.0):
    root = _safe_path(skills_root)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError("skills 根目录不存在")
    lock_path = _safe_path(root / LOCK)
    descriptor = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("更新锁不是普通文件")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("另一个技能安装或更新正在运行，请稍后重试")
                time.sleep(0.05)
        yield root
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _transaction_path(root, transaction):
    if not isinstance(transaction, str) or not re.fullmatch(r"[0-9a-f]{32}", transaction):
        raise ValueError("事务编号无效")
    return _safe_path(_safe_path(root) / CONTROL / transaction)


def _read_journal(path):
    journal_path = _safe_path(path / "journal.json")
    try:
        data = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("更新事务记录无法读取，请保留目录后人工检查：{}".format(path)) from error
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 or
            data.get("transaction") != path.name or data.get("operation") not in ("update", "rollback") or
            data.get("state") not in FINAL_STATES | {"prepared", "old_saved", "new_published", "recovering"}):
        raise ValueError("不支持或损坏的更新事务记录：{}".format(path))
    for name in ("before", "after"):
        snapshot = data.get(name)
        if (not isinstance(snapshot, dict) or
                not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("fingerprint", "")))):
            raise ValueError("更新事务缺少有效内容指纹")
    return data


def _journals(root):
    control = _safe_path(_safe_path(root) / CONTROL)
    if not control.exists():
        return []
    if not control.is_dir():
        raise ValueError("更新备份路径不是目录")
    result = []
    for path in sorted(control.iterdir()):
        if not path.is_dir() or path.is_symlink():
            raise ValueError("更新备份目录包含未知内容：{}".format(path.name))
        _transaction_path(root, path.name)
        # 写入 journal 前只创建并复制临时包，不会改动安装目录。
        if not (path / "journal.json").exists():
            continue
        result.append((path, _read_journal(path)))
    return result


def assert_no_pending(root):
    pending = [data["transaction"] for _, data in _journals(root) if data["state"] not in FINAL_STATES]
    if pending:
        raise ValueError("存在未完成更新 {}，请先执行 recover".format(", ".join(pending)))


def _ensure_separate(source, destination, control):
    for other in (destination, control):
        if source == other or source in other.parents or other in source.parents:
            raise ValueError("更新来源不能与安装或备份目录重叠")


def _check_versions(before, after):
    if before["kind"] == "legacy-untracked":
        return
    comparison = release.compare_versions(after["version"], before["version"])
    if comparison < 0:
        raise ValueError("拒绝降级；恢复以前的运行包请使用 rollback")
    if comparison == 0 and before["fingerprint"] != after["fingerprint"]:
        raise ValueError("相同产品版本存在不同内容，拒绝覆盖；请发布新的版本号")


def update_plan(package, skills_root):
    root = _safe_path(skills_root)
    source = _safe_path(package)
    destination = _safe_path(root / release.PACKAGE_NAME)
    _ensure_separate(source, destination, root / CONTROL)
    assert_no_pending(root)
    release.verify(source)
    after, before = _snapshot(source), _snapshot(destination)
    _check_versions(before, after)
    return {"status": "unchanged" if before["fingerprint"] == after["fingerprint"] else "planned",
            "operation": "update", "path": str(destination), "source": str(source),
            "current": before, "target": after, "expected_current": before["fingerprint"],
            "expected_source": after["fingerprint"], "writers_must_be_stopped": True,
            "backup_root": str(root / CONTROL), "project_data_changed": False}


def _require_stopped(writers_stopped):
    if not writers_stopped:
        raise ValueError("请先停止使用旧/新技能写入项目的 Agent，再明确传入 --writers-stopped")


def _match(snapshot, expected, label):
    if snapshot["fingerprint"] != expected:
        raise ValueError("{}内容已变化，旧计划不能执行；请重新生成计划".format(label))


def _event(name, journal):
    """测试可注入异常或进程中断，不提供环境变量故障开关。"""


def _save(path, journal, state):
    journal["state"] = state
    _write_json(path / "journal.json", journal)
    _event(state, journal)


def _rename(source, destination):
    release._rename_new(source, destination)
    _sync(source.parent)
    if source.parent != destination.parent:
        _sync(destination.parent)


def _same_snapshot(path, expected):
    return _snapshot(path)["fingerprint"] == expected["fingerprint"]


def _recover_one(root, path, journal):
    destination = _safe_path(root / release.PACKAGE_NAME)
    before = _safe_path(path / "before")
    displaced = _safe_path(path / "displaced")
    original_state = journal["state"]
    if original_state in FINAL_STATES:
        return {"transaction": path.name, "status": original_state}
    if before.exists() and not _same_snapshot(before, journal["before"]):
        raise ValueError("更新备份已变化，拒绝自动恢复：{}".format(path.name))
    if destination.exists():
        snapshot = _snapshot(destination)
        if snapshot["fingerprint"] == journal["before"]["fingerprint"]:
            _save(path, journal, "recovered")
            return {"transaction": path.name, "status": "recovered"}
        if snapshot["fingerprint"] != journal["after"]["fingerprint"]:
            raise ValueError("安装目录在中断后被修改，拒绝自动覆盖；保留现场：{}".format(path.name))
        if not before.exists():
            raise ValueError("缺少原安装备份，拒绝自动恢复")
        if displaced.exists():
            raise ValueError("恢复暂存目录已存在，保留现场供人工检查")
        _save(path, journal, "recovering")
        _rename(destination, displaced)
    if not before.exists():
        raise ValueError("安装目录和原备份均不可用，保留事务供人工检查")
    # 先复制备份再排他发布，恢复后仍完整保留更新前的备份。
    restored = _safe_path(path / "restoring")
    if restored.exists():
        try:
            valid = _same_snapshot(restored, journal["before"])
        except (OSError, ValueError):
            valid = False
        if not valid:
            _rename(restored, path / ("incomplete-" + uuid.uuid4().hex))
    if not restored.exists():
        shutil.copytree(before, restored, symlinks=True)
        _sync_tree(restored)
    if not _same_snapshot(restored, journal["before"]) or not _same_snapshot(before, journal["before"]):
        raise ValueError("恢复期间备份内容变化，拒绝发布")
    _rename(restored, destination)
    if not _same_snapshot(destination, journal["before"]):
        raise ValueError("恢复后内容核查失败，保留事务供人工检查")
    _save(path, journal, "recovered")
    return {"transaction": path.name, "status": "recovered"}


def _switch(root, source, before, after, operation, related=None):
    control = _safe_path(root / CONTROL)
    control.mkdir(mode=0o700, exist_ok=True)
    _sync(root)
    transaction = uuid.uuid4().hex
    path = control / transaction
    path.mkdir(mode=0o700)
    _sync(control)
    incoming = path / "incoming"
    destination = _safe_path(root / release.PACKAGE_NAME)
    journal = {"schema_version": 1, "transaction": transaction, "operation": operation,
               "created_at": datetime.now(timezone.utc).isoformat(), "state": "prepared",
               "before": before, "after": after, "related_transaction": related}
    try:
        shutil.copytree(source, incoming, symlinks=True)
        _sync_tree(incoming)
        _match(_snapshot(incoming), after["fingerprint"], "复制后的交付包")
        _match(_snapshot(source), after["fingerprint"], "来源")
        _match(_snapshot(destination), before["fingerprint"], "当前安装")
        _save(path, journal, "prepared")
        _match(_snapshot(source), after["fingerprint"], "来源")
        _match(_snapshot(destination), before["fingerprint"], "当前安装")
        _rename(destination, path / "before")
        _event("after_old_rename", journal)
        _save(path, journal, "old_saved")
        _match(_snapshot(path / "before"), before["fingerprint"], "原安装备份")
        _rename(incoming, destination)
        _event("after_new_rename", journal)
        _save(path, journal, "new_published")
        _match(_snapshot(destination), after["fingerprint"], "更新后安装")
        _match(_snapshot(path / "before"), before["fingerprint"], "原安装备份")
        _save(path, journal, "committed")
    except Exception as error:
        if (path / "journal.json").exists():
            saved = _read_journal(path)
            if saved["state"] == "committed":
                raise ValueError("事务 {} 已记录完成，但收尾发生异常；请核验当前安装后重试同一命令：{}".format(
                    transaction, error)) from error
            try:
                _recover_one(root, path, saved)
            except Exception as recovery_error:
                raise ValueError("更新失败且自动恢复未完成；保留事务 {}，请执行 recover：{}；原错误：{}".format(
                    transaction, recovery_error, error)) from error
        raise
    return {"status": "updated" if operation == "update" else "rolled_back", "transaction": transaction,
            "path": str(destination), "backup": str(path / "before"), "current": after,
            "project_data_changed": False}


def update(package, skills_root, expected_current, expected_source, writers_stopped=False):
    _require_stopped(writers_stopped)
    with installation_lock(skills_root) as root:
        plan = update_plan(package, root)
        _match(plan["target"], expected_source, "来源")
        if plan["status"] == "unchanged":
            return {"status": "unchanged", "path": plan["path"], "current": plan["current"]}
        _match(plan["current"], expected_current, "当前安装")
        return _switch(root, _safe_path(package), plan["current"], plan["target"], "update")


def rollback_plan(skills_root, transaction):
    root = _safe_path(skills_root)
    assert_no_pending(root)
    path = _transaction_path(root, transaction)
    journal = _read_journal(path)
    if journal["state"] != "committed":
        raise ValueError("只有已完成切换的事务可以回滚")
    current = _snapshot(root / release.PACKAGE_NAME)
    backup = _snapshot(path / "before")
    _match(backup, journal["before"]["fingerprint"], "回滚备份")
    unchanged = current["fingerprint"] == backup["fingerprint"]
    if not unchanged:
        _match(current, journal["after"]["fingerprint"], "当前安装")
    return {"status": "unchanged" if unchanged else "planned", "operation": "rollback", "transaction": transaction,
            "current": current, "target": backup, "expected_current": current["fingerprint"],
            "backup": str(path / "before"), "writers_must_be_stopped": True, "project_data_changed": False}


def rollback(skills_root, transaction, expected_current, writers_stopped=False):
    _require_stopped(writers_stopped)
    with installation_lock(skills_root) as root:
        plan = rollback_plan(root, transaction)
        if plan["status"] == "unchanged":
            return {"status": "unchanged", "path": str(root / release.PACKAGE_NAME),
                    "current": plan["current"], "project_data_changed": False}
        _match(plan["current"], expected_current, "当前安装")
        return _switch(root, _safe_path(plan["backup"]), plan["current"], plan["target"], "rollback", transaction)


def recover(skills_root, writers_stopped=False):
    _require_stopped(writers_stopped)
    with installation_lock(skills_root) as root:
        pending = [(path, data) for path, data in _journals(root) if data["state"] not in FINAL_STATES]
        if len(pending) > 1:
            raise ValueError("存在多个未完成事务，拒绝猜测恢复顺序；请保留现场人工检查")
        results = [_recover_one(root, path, data) for path, data in pending]
        return {"status": "recovered" if results else "unchanged", "transactions": results,
                "project_data_changed": False}


def add_commands(commands):
    plan = commands.add_parser("update-plan", help="只读检查来源和安装内容，生成绑定指纹的更新计划")
    plan.add_argument("package", type=Path, help="已解压、已校验的新版本目录")
    execution = commands.add_parser("update", help="备份并连续更新技能运行包；不修改项目工作流")
    execution.add_argument("package", type=Path, help="与更新计划一致的新版本目录")
    execution.add_argument("--expected-current", required=True, help="update-plan 返回的当前安装指纹")
    execution.add_argument("--expected-source", required=True, help="update-plan 返回的来源指纹")
    rollback_plan_parser = commands.add_parser("rollback-plan", help="只读检查指定更新的回滚条件")
    rollback_parser = commands.add_parser("rollback", help="恢复指定事务前的技能运行包，保留全部备份")
    for command in (rollback_plan_parser, rollback_parser):
        command.add_argument("--transaction", required=True, help="更新成功后返回的事务编号")
    rollback_parser.add_argument("--expected-current", required=True, help="rollback-plan 返回的当前安装指纹")
    recovery = commands.add_parser("recover", help="恢复未完成事务之前的运行包，不覆盖后来修改的内容")
    for command in (plan, execution, rollback_plan_parser, rollback_parser, recovery):
        command.add_argument("--skills-root", type=Path, required=True, help="明确指定 skills 根目录")
    for command in (execution, rollback_parser, recovery):
        command.add_argument("--writers-stopped", action="store_true", help="确认使用新旧版本写入项目的 Agent 均已停止")


def dispatch(args):
    if args.command == "update-plan":
        return update_plan(args.package, args.skills_root)
    if args.command == "update":
        return update(args.package, args.skills_root, args.expected_current, args.expected_source, args.writers_stopped)
    if args.command == "rollback-plan":
        return rollback_plan(args.skills_root, args.transaction)
    if args.command == "rollback":
        return rollback(args.skills_root, args.transaction, args.expected_current, args.writers_stopped)
    if args.command == "recover":
        return recover(args.skills_root, args.writers_stopped)
    raise ValueError("未知更新命令")
