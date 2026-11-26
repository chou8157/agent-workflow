"""连续更新和恢复测试：只使用临时安装目录。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile

import pytest

from experiments.frontier import build_release as release
from experiments.frontier import release_update as updater


@pytest.fixture
def package(tmp_path):
    package = tmp_path / "package"
    release.build(package)
    return package


@pytest.fixture
def legacy(tmp_path):
    root = tmp_path / "skills"
    installed = root / release.PACKAGE_NAME
    (installed / "scripts/__pycache__").mkdir(parents=True)
    (installed / "SKILL.md").write_text("---\nname: agent-workflow\ndescription: 旧工作流\n---\n# 用户原版\n", encoding="utf-8")
    (installed / "scripts/old.py").write_text("print('旧程序')\n", encoding="utf-8")
    (installed / "scripts/__pycache__/old.pyc").write_bytes(b"legacy-cache")
    (installed / "custom.txt").write_text("自定义内容必须完整保留\n", encoding="utf-8")
    return root


def _hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _new_version(package, path, version):
    shutil.copytree(package, path)
    (path / "VERSION").write_text(version + "\n", encoding="utf-8")
    notes = (path / release.RELEASE_NOTES).read_text(encoding="utf-8").splitlines(keepends=True)
    notes[0] = "# {} {}\n".format(release.PACKAGE_NAME, version)
    (path / release.RELEASE_NOTES).write_text("".join(notes), encoding="utf-8")
    _refresh_manifest(path, version)
    release.verify(path)
    return path


def _refresh_manifest(path, version):
    info = json.loads((path / release.RELEASE_INFO).read_text(encoding="utf-8"))
    info["version"] = version
    info["channel"] = release._channel(version)
    info["source"]["content_sha256"] = release._payload_digest(release._manifest(path, version))
    (path / release.RELEASE_INFO).write_bytes(release._canonical(info))
    manifest = release._manifest(path, version)
    (path / release.MANIFEST).write_bytes(release._canonical(manifest))


def _apply(package, root):
    plan = updater.update_plan(package, root)
    return updater.update(package, root, plan["expected_current"], plan["expected_source"], True)


def test_legacy_plan_is_read_only_and_upgrade_keeps_complete_backup(package, legacy, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "state.json").write_text('{"keep": true}', encoding="utf-8")
    original = _hashes(legacy)
    project_before = _hashes(project)
    plan = updater.update_plan(package, legacy)
    assert plan["current"]["kind"] == "legacy-untracked"
    assert plan["current"]["version"] is None
    assert plan["writers_must_be_stopped"]
    assert _hashes(legacy) == original
    assert not (legacy / updater.CONTROL).exists()
    result = updater.update(package, legacy, plan["expected_current"], plan["expected_source"], True)
    assert result["status"] == "updated"
    assert {release.PACKAGE_NAME + "/" + name: digest for name, digest in _hashes(Path(result["backup"])).items()} == original
    assert release.verify(legacy / release.PACKAGE_NAME) == release.verify(package)
    assert _hashes(project) == project_before


def test_multiple_versions_verify_and_update_without_current_version_constant(package, legacy, tmp_path):
    first = _apply(package, legacy)
    newer = _new_version(package, tmp_path / "next", "1.3.0")
    newest = _new_version(package, tmp_path / "newest", "2.0.0-beta.2")
    second, third = _apply(newer, legacy), _apply(newest, legacy)
    assert len({first["transaction"], second["transaction"], third["transaction"]}) == 3
    assert release.verify(legacy / release.PACKAGE_NAME)["version"] == "2.0.0-beta.2"
    assert release.verify(Path(second["backup"]))["version"] == release.read_product_version()
    assert release.verify(Path(third["backup"]))["version"] == "1.3.0"
    before = _hashes(legacy)
    assert _apply(newest, legacy)["status"] == "unchanged"
    assert _hashes(legacy) == before


def test_retry_exact_update_command_after_success_is_unchanged(package, legacy):
    plan = updater.update_plan(package, legacy)
    updater.update(package, legacy, plan["expected_current"], plan["expected_source"], True)
    before = _hashes(legacy)
    retry = updater.update(package, legacy, plan["expected_current"], plan["expected_source"], True)
    assert retry["status"] == "unchanged"
    assert _hashes(legacy) == before


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0-alpha.9", "1.1.0-beta.0"])
def test_normal_update_refuses_downgrade(package, legacy, tmp_path, version):
    _apply(package, legacy)
    older = _new_version(package, tmp_path / "older", version)
    before = _hashes(legacy)
    with pytest.raises(ValueError, match="降级"):
        updater.update_plan(older, legacy)
    assert _hashes(legacy) == before


def test_same_version_changed_payload_and_future_schema_are_rejected(package, legacy, tmp_path):
    _apply(package, legacy)
    changed = _new_version(package, tmp_path / "changed", release.read_product_version())
    (changed / "SKILL.md").write_text((changed / "SKILL.md").read_text(encoding="utf-8") + "\n变化\n", encoding="utf-8")
    _refresh_manifest(changed, release.read_product_version())
    with pytest.raises(ValueError, match="相同产品版本"):
        updater.update_plan(changed, legacy)
    future = json.loads((changed / release.MANIFEST).read_text(encoding="utf-8"))
    future["schema_version"] = 999
    (changed / release.MANIFEST).write_bytes(release._canonical(future))
    with pytest.raises(ValueError, match="不受支持"):
        updater.update_plan(changed, legacy)


def test_plan_bound_to_both_sides_and_requires_stopped_writers(package, legacy):
    plan = updater.update_plan(package, legacy)
    with pytest.raises(ValueError, match="writers-stopped"):
        updater.update(package, legacy, plan["expected_current"], plan["expected_source"])
    with pytest.raises(ValueError, match="来源内容已变化"):
        updater.update(package, legacy, plan["expected_current"], "0" * 64, True)
    (legacy / release.PACKAGE_NAME / "custom.txt").write_text("计划后编辑", encoding="utf-8")
    with pytest.raises(ValueError, match="当前安装内容已变化"):
        updater.update(package, legacy, plan["expected_current"], plan["expected_source"], True)
    assert not (legacy / updater.CONTROL).exists()


def test_staging_rechecks_source_and_destination_before_switch(package, legacy, monkeypatch):
    plan = updater.update_plan(package, legacy)
    original = _hashes(legacy / release.PACKAGE_NAME)
    real_event = updater._event

    def change_after_copy(name, journal):
        if name == "prepared":
            (package / "SKILL.md").write_text("来源在计划后变化", encoding="utf-8")
        real_event(name, journal)

    monkeypatch.setattr(updater, "_event", change_after_copy)
    with pytest.raises(ValueError):
        updater.update(package, legacy, plan["expected_current"], plan["expected_source"], True)
    assert _hashes(legacy / release.PACKAGE_NAME) == original


@pytest.mark.parametrize("event", ["prepared", "after_old_rename", "old_saved", "after_new_rename", "new_published"])
def test_exception_at_switch_boundaries_restores_before_install(package, legacy, monkeypatch, event):
    original = _hashes(legacy / release.PACKAGE_NAME)

    def fail_once(name, journal):
        if name == event:
            raise RuntimeError("受控失败")

    monkeypatch.setattr(updater, "_event", fail_once)
    with pytest.raises(RuntimeError, match="受控失败"):
        _apply(package, legacy)
    assert _hashes(legacy / release.PACKAGE_NAME) == original
    assert updater.recover(legacy, True)["status"] == "unchanged"
    assert all(journal["state"] == "recovered" for _, journal in updater._journals(legacy))


@pytest.mark.parametrize("event", ["prepared", "after_old_rename", "old_saved", "after_new_rename", "new_published"])
def test_killed_process_recovery_keeps_backups_and_is_idempotent(package, legacy, event, tmp_path):
    original = _hashes(legacy / release.PACKAGE_NAME)
    code = """
import os, signal, sys
from experiments.frontier import release_update as u
u._event = lambda name, journal: os.kill(os.getpid(), signal.SIGKILL) if name == sys.argv[3] else None
p = u.update_plan(sys.argv[1], sys.argv[2])
u.update(sys.argv[1], sys.argv[2], p['expected_current'], p['expected_source'], True)
"""
    process = subprocess.run([sys.executable, "-B", "-c", code, str(package), str(legacy), event],
                             cwd=release.REPOSITORY, capture_output=True, text=True)
    assert process.returncode == -signal.SIGKILL, process.stderr
    with pytest.raises(ValueError, match="recover"):
        updater.update_plan(package, legacy)
    result = updater.recover(legacy, True)
    assert result["status"] == "recovered"
    assert _hashes(legacy / release.PACKAGE_NAME) == original
    before = _hashes(legacy)
    assert updater.recover(legacy, True)["status"] == "unchanged"
    assert _hashes(legacy) == before
    assert _apply(package, legacy)["status"] == "updated"


def test_rollback_restores_legacy_and_keeps_both_versions(package, legacy):
    original = _hashes(legacy / release.PACKAGE_NAME)
    result = _apply(package, legacy)
    plan = updater.rollback_plan(legacy, result["transaction"])
    rolled = updater.rollback(legacy, result["transaction"], plan["expected_current"], True)
    assert rolled["status"] == "rolled_back"
    assert _hashes(legacy / release.PACKAGE_NAME) == original
    assert _hashes(Path(result["backup"])) == original
    release.verify(Path(rolled["backup"]))
    before_retry = _hashes(legacy)
    assert updater.rollback(legacy, result["transaction"], plan["expected_current"], True)["status"] == "unchanged"
    assert _hashes(legacy) == before_retry
    assert _apply(package, legacy)["status"] == "updated"


def test_rollback_refuses_later_update_or_manual_edit(package, legacy, tmp_path):
    first = _apply(package, legacy)
    newer = _new_version(package, tmp_path / "newer", "1.3.0")
    second = _apply(newer, legacy)
    with pytest.raises(ValueError, match="当前安装内容已变化"):
        updater.rollback_plan(legacy, first["transaction"])
    plan = updater.rollback_plan(legacy, second["transaction"])
    (legacy / release.PACKAGE_NAME / "SKILL.md").write_text("后续人工修改", encoding="utf-8")
    changed = _hashes(legacy)
    with pytest.raises(ValueError):
        updater.rollback(legacy, second["transaction"], plan["expected_current"], True)
    assert _hashes(legacy) == changed


def test_restore_refuses_modified_installed_package_after_interruption(package, legacy, monkeypatch):
    def stop_after_publish(name, journal):
        if name == "after_new_rename":
            raise KeyboardInterrupt()

    monkeypatch.setattr(updater, "_event", stop_after_publish)
    with pytest.raises(KeyboardInterrupt):
        _apply(package, legacy)
    (legacy / release.PACKAGE_NAME / "user.txt").write_text("必须保留", encoding="utf-8")
    before = _hashes(legacy)
    with pytest.raises(ValueError):
        updater.recover(legacy, True)
    assert _hashes(legacy) == before


def test_interrupted_restore_copy_can_be_retried_without_discarding_backup(package, legacy, monkeypatch):
    original = _hashes(legacy / release.PACKAGE_NAME)

    def interrupt(name, journal):
        if name == "old_saved":
            raise KeyboardInterrupt()

    monkeypatch.setattr(updater, "_event", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _apply(package, legacy)
    path, _ = updater._journals(legacy)[0]
    (path / "restoring").mkdir()
    (path / "restoring/partial.txt").write_text("中断的复制", encoding="utf-8")
    updater.recover(legacy, True)
    assert _hashes(legacy / release.PACKAGE_NAME) == original
    assert _hashes(path / "before") == original
    assert list(path.glob("incomplete-*"))


@pytest.mark.parametrize("where", ["source", "destination", "control", "parent", "lock"])
def test_symbolic_paths_are_rejected(package, legacy, tmp_path, where):
    target = legacy / release.PACKAGE_NAME
    if where == "source":
        link = tmp_path / "linked-package"
        link.symlink_to(package, target_is_directory=True)
        package = link
    elif where == "destination":
        other = tmp_path / "old"
        target.rename(other)
        target.symlink_to(other, target_is_directory=True)
    elif where == "control":
        (legacy / updater.CONTROL).symlink_to(tmp_path, target_is_directory=True)
    elif where == "parent":
        link = tmp_path / "linked-parent"
        link.symlink_to(legacy, target_is_directory=True)
        legacy = link
    else:
        (legacy / updater.LOCK).symlink_to(tmp_path / "unrelated")
    with pytest.raises(ValueError, match="符号链接"):
        _apply(package, legacy)


def test_packaged_update_and_rollback_run_outside_repository(package, legacy, tmp_path):
    installer = package / "scripts/release_package.py"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    def run(*args):
        process = subprocess.run([sys.executable, str(installer), *map(str, args)], cwd=tmp_path,
                                 env=environment, text=True, capture_output=True)
        assert process.returncode == 0, process.stdout + process.stderr
        return json.loads(process.stdout.split("：", 1)[1])

    before = _hashes(legacy / release.PACKAGE_NAME)
    plan = run("update-plan", package, "--skills-root", legacy)
    result = run("update", package, "--skills-root", legacy, "--expected-current", plan["expected_current"],
                 "--expected-source", plan["expected_source"], "--writers-stopped")
    run("verify", legacy / release.PACKAGE_NAME)
    rollback_plan = run("rollback-plan", "--skills-root", legacy, "--transaction", result["transaction"])
    run("rollback", "--skills-root", legacy, "--transaction", result["transaction"],
        "--expected-current", rollback_plan["expected_current"], "--writers-stopped")
    assert _hashes(legacy / release.PACKAGE_NAME) == before
    release.verify(package)


def test_concurrent_updaters_publish_once_and_repeat_idempotently(package, legacy, tmp_path):
    plan = updater.update_plan(package, legacy)
    command = [sys.executable, "-B", str(package / "scripts/release_package.py"), "update", str(package),
               "--skills-root", str(legacy), "--expected-current", plan["expected_current"],
               "--expected-source", plan["expected_source"], "--writers-stopped"]
    processes = [subprocess.Popen(command, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(2)]
    outputs = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], outputs
    statuses = [json.loads(stdout.split("：", 1)[1])["status"] for stdout, _ in outputs]
    assert sorted(statuses) == ["unchanged", "updated"]
    release.verify(legacy / release.PACKAGE_NAME)
    assert len(updater._journals(legacy)) == 1


def test_concurrent_different_candidates_cannot_overwrite_with_stale_plan(package, legacy, tmp_path):
    later = _new_version(package, tmp_path / "later", "1.3.0")
    candidates = [package, later]
    plans = [updater.update_plan(candidate, legacy) for candidate in candidates]
    processes = []
    for candidate, plan in zip(candidates, plans):
        command = [sys.executable, "-B", str(package / "scripts/release_package.py"), "update", str(candidate),
                   "--skills-root", str(legacy), "--expected-current", plan["expected_current"],
                   "--expected-source", plan["expected_source"], "--writers-stopped"]
        processes.append(subprocess.Popen(command, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    outputs = [process.communicate(timeout=30) for process in processes]
    assert sorted(process.returncode for process in processes) == [0, 2], outputs
    release.verify(legacy / release.PACKAGE_NAME)
    assert len(updater._journals(legacy)) == 1


@pytest.mark.parametrize("left,right,result", [("1.1.0", "1.1.0-beta.1", 1), ("1.1.0-beta.2", "1.1.0-beta.10", -1),
                                               ("1.1.0-beta", "1.1.0-beta.1", -1), ("1.1.0+one", "1.1.0+two", 0)])
def test_semantic_version_ordering(left, right, result):
    assert release.compare_versions(left, right) == result


def test_prior_manifest_does_not_require_current_runtime_modules(package, tmp_path):
    root = tmp_path / "skills"
    installed = root / release.PACKAGE_NAME
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text("---\nname: agent-workflow\ndescription: 历史包\n---\n旧正文\n", encoding="utf-8")
    (installed / release.MANIFEST).write_bytes(release._canonical(release._manifest(installed, "0.8.0")))
    assert release.verify(installed)["version"] == "0.8.0"
    assert _apply(package, root)["status"] == "updated"


def test_staging_io_failure_leaves_install_untouched(package, legacy, monkeypatch):
    original = _hashes(legacy / release.PACKAGE_NAME)

    def fail_copy(source, destination, **kwargs):
        Path(destination).mkdir()
        (Path(destination) / "partial.txt").write_text("磁盘写入中断", encoding="utf-8")
        raise OSError("模拟磁盘空间不足")

    monkeypatch.setattr(shutil, "copytree", fail_copy)
    with pytest.raises(OSError, match="磁盘空间不足"):
        _apply(package, legacy)
    assert _hashes(legacy / release.PACKAGE_NAME) == original
    assert updater.recover(legacy, True)["status"] == "unchanged"


def test_interrupted_rollback_recovers_the_version_before_rollback(package, legacy, monkeypatch):
    result = _apply(package, legacy)
    installed_before = _hashes(legacy / release.PACKAGE_NAME)
    plan = updater.rollback_plan(legacy, result["transaction"])

    def interrupt(name, journal):
        if name == "after_new_rename":
            raise KeyboardInterrupt()

    monkeypatch.setattr(updater, "_event", interrupt)
    with pytest.raises(KeyboardInterrupt):
        updater.rollback(legacy, result["transaction"], plan["expected_current"], True)
    assert updater.recover(legacy, True)["status"] == "recovered"
    assert _hashes(legacy / release.PACKAGE_NAME) == installed_before


def test_second_lock_holder_times_out_cleanly(package, legacy):
    with updater.installation_lock(legacy):
        with pytest.raises(ValueError, match="另一个技能"):
            with updater.installation_lock(legacy, timeout=0.01):
                raise AssertionError("不应获得第二个独立文件锁")


def test_commit_reply_failure_can_be_retried_with_original_plan(package, legacy, monkeypatch):
    plan = updater.update_plan(package, legacy)

    def fail_reply(name, journal):
        if name == "committed":
            raise OSError("模拟完成后报告失败")

    monkeypatch.setattr(updater, "_event", fail_reply)
    with pytest.raises(ValueError, match="已记录完成"):
        updater.update(package, legacy, plan["expected_current"], plan["expected_source"], True)
    assert updater.update(package, legacy, plan["expected_current"], plan["expected_source"], True)["status"] == "unchanged"


def test_extracted_archive_and_build_directory_have_identical_update_identity(package, legacy, tmp_path):
    _apply(package, legacy)
    archive = tmp_path / "release.tar.gz"
    release.archive(package, archive)
    extracted = tmp_path / "extracted"
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(extracted)
    from_archive = extracted / release.PACKAGE_NAME
    assert updater._snapshot(package) == updater._snapshot(from_archive)
    assert updater.update_plan(from_archive, legacy)["status"] == "unchanged"
    assert _apply(from_archive, legacy)["status"] == "unchanged"


def test_release_identity_does_not_depend_on_build_umask(package, tmp_path):
    other = tmp_path / "restricted-build"
    previous = os.umask(0o077)
    try:
        release.build(other)
    finally:
        os.umask(previous)
    assert updater._snapshot(other) == updater._snapshot(package)
