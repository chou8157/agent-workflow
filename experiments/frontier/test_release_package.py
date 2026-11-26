"""独立交付包验收：全部写入临时目录，不触碰实际 skills 安装。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from experiments.frontier import build_release as release


@pytest.fixture
def package(tmp_path):
    destination = tmp_path / "bundle"
    release.build(destination)
    return destination


def _hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _run(script, cwd, *arguments):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    return subprocess.run([sys.executable, str(script), *map(str, arguments)], cwd=cwd,
                          env=environment, capture_output=True, text=True)


def _assert_ok(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_build_repeats_without_changes_and_contains_only_runtime_assets(package):
    before = _hashes(package)
    timestamps = {path.relative_to(package).as_posix(): path.stat().st_mtime_ns
                  for path in package.rglob("*") if path.is_file()}
    result = release.build(package)
    assert result["status"] == "unchanged"
    assert _hashes(package) == before
    assert timestamps == {path.relative_to(package).as_posix(): path.stat().st_mtime_ns
                          for path in package.rglob("*") if path.is_file()}
    manifest = release.verify(package)
    assert manifest["name"] == "agent-workflow" and manifest["version"] == release.read_product_version()
    assert not (package / "references/local-workflow.md").read_text(encoding="utf-8").startswith("---")
    assert all(not any(part in ("__pycache__", "tests", "experiments", "evidence", "fixtures") for part in Path(name).parts)
               for name in manifest["files"])
    assert all(not Path(name).name.startswith("test_") for name in manifest["files"])


def test_install_is_separate_atomic_and_idempotent_from_any_working_directory(package, tmp_path):
    root = tmp_path / "skills"
    stable = root / "agent-workflow-frontier"
    stable.mkdir(parents=True)
    (stable / "SKILL.md").write_text("已有稳定版，必须保留。\n", encoding="utf-8")
    original = _hashes(stable)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    installer = package / "scripts/release_package.py"
    _assert_ok(_run(installer, outside, "install", package, "--skills-root", root))
    destination = root / release.PACKAGE_NAME
    before = _hashes(destination)
    repeated = _assert_ok(_run(destination / "scripts/release_package.py", outside,
                               "install", package, "--skills-root", root))
    assert "unchanged" in repeated.stdout
    assert _hashes(destination) == before
    assert _hashes(stable) == original
    assert not list(root.glob(".*-install-*"))
    _assert_ok(_run(destination / "scripts/release_package.py", outside, "verify", destination))


def test_package_is_self_contained_for_local_and_three_level_workflow(package, tmp_path):
    outside = tmp_path / "arbitrary-cwd"
    outside.mkdir()
    release.install(package, tmp_path / "skills")
    installed = tmp_path / "skills" / release.PACKAGE_NAME
    scripts = installed / "scripts"
    cli = scripts / "frontier/light_cli.py"
    package_before = _hashes(installed)
    for script in (cli, scripts / "scaffold_workflow.py", scripts / "task_context.py",
                   scripts / "finalize_context.py", scripts / "capability_context.py"):
        _assert_ok(_run(script, outside, "--help"))
    nodes = tmp_path / "projects"
    registry = tmp_path / "control/registry.sqlite"
    for node in ("root", "middle", "leaf"):
        project = nodes / node
        _assert_ok(_run(scripts / "scaffold_workflow.py", outside, project))
        _assert_ok(_run(scripts / "task_context.py", outside, project, "create", "W-package", "--title", "独立包验收"))
        evidence = project / ".agent-workflow/30-records/work-items/W-package/validation-log.md"
        evidence.write_text("# 验证记录\n本地接口验证通过。\n", encoding="utf-8")
        _assert_ok(_run(cli, outside, "record", "--project", project, "--item", "W-package",
                        "--date", "2026-10-15", "--summary", "{} 完成本地验收".format(node),
                        "--status", "completed", "--evidence", evidence.relative_to(project),
                        "--line-start", "2", "--line-end", "2"))
        assert not (project / ".frontier-node.json").exists()
    _assert_ok(_run(cli, outside, "connect", "--project", nodes / "root", "--registry", registry))
    _assert_ok(_run(cli, outside, "connect", "--project", nodes / "middle", "--parent", nodes / "root"))
    _assert_ok(_run(cli, outside, "connect", "--project", nodes / "leaf", "--parent", nodes / "middle"))
    sources_before = _hashes(nodes)
    report = _assert_ok(_run(cli, outside, "report", "--project", nodes / "root", "--source-root", nodes,
                            "--start", "2026-10-13", "--end", "2026-10-19"))
    assert all("{} 完成本地验收".format(node) in report.stdout for node in ("root", "middle", "leaf"))
    assert _hashes(nodes) == sources_before
    assert _hashes(installed) == package_before
    release.verify(installed)


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra", "empty-directory", "symlink"])
def test_verify_and_install_refuse_modified_or_incomplete_package(package, tmp_path, mutation):
    target = package / "scripts/frontier/light_cli.py"
    if mutation == "changed":
        target.write_text(target.read_text(encoding="utf-8") + "\n# 内容变化\n", encoding="utf-8")
    elif mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (package / "unexpected.txt").write_text("多余文件", encoding="utf-8")
    elif mutation == "empty-directory":
        (package / "unexpected-directory").mkdir()
    else:
        external = tmp_path / "external.py"
        external.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(external)
    with pytest.raises(ValueError):
        release.verify(package)
    skills = tmp_path / "not-created"
    with pytest.raises(ValueError):
        release.install(package, skills)
    assert not skills.exists()


def test_install_refuses_existing_different_files_and_symbolic_targets(package, tmp_path):
    root = tmp_path / "skills"
    existing = root / release.PACKAGE_NAME
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("用户原文件\n", encoding="utf-8")
    before = _hashes(existing)
    with pytest.raises(ValueError):
        release.install(package, root)
    assert _hashes(existing) == before

    linked = tmp_path / "linked-skills"
    linked.mkdir()
    (linked / release.PACKAGE_NAME).symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        release.install(package, linked)
    assert _hashes(existing) == before


def test_install_rechecks_temporary_copy_before_publication(package, tmp_path, monkeypatch):
    real_copytree = shutil.copytree

    def corrupted_copy(source, destination, *args, **kwargs):
        result = real_copytree(source, destination, *args, **kwargs)
        if Path(source) == package:
            (Path(destination) / "SKILL.md").write_text("复制后内容发生变化", encoding="utf-8")
        return result

    monkeypatch.setattr(shutil, "copytree", corrupted_copy)
    root = tmp_path / "skills"
    with pytest.raises(ValueError):
        release.install(package, root)
    assert not (root / release.PACKAGE_NAME).exists()
    assert not list(root.glob(".*-install-*"))


def test_two_independent_installers_do_not_overwrite_each_other(package, tmp_path):
    root = tmp_path / "skills"
    command = [sys.executable, str(package / "scripts/release_package.py"), "install", str(package), "--skills-root", str(root)]
    first = subprocess.Popen(command, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    second = subprocess.Popen(command, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    first_out, first_err = first.communicate(timeout=30)
    second_out, second_err = second.communicate(timeout=30)
    assert first.returncode == second.returncode == 0, first_err + second_err
    assert "created" in first_out + second_out and "unchanged" in first_out + second_out
    release.verify(root / release.PACKAGE_NAME)


def test_archive_is_repeatable_and_can_be_extracted_independently(package, tmp_path):
    archive = tmp_path / "frontier.tar.gz"
    initial = release.archive(package, archive)
    repeated = release.archive(package, archive)
    assert initial["status"] == "created" and repeated["status"] == "unchanged"
    assert initial["sha256"] == repeated["sha256"]
    extracted = tmp_path / "extracted"
    with tarfile.open(archive, "r:gz") as bundle:
        assert all(member.name == release.PACKAGE_NAME or member.name.startswith(release.PACKAGE_NAME + "/")
                   for member in bundle.getmembers())
        assert all(member.isfile() or member.isdir() for member in bundle.getmembers())
        bundle.extractall(extracted)
    assert release.verify(extracted / release.PACKAGE_NAME) == release.verify(package)
    assert _hashes(extracted / release.PACKAGE_NAME) == _hashes(package)


def test_manifest_cannot_target_a_different_skill(package, tmp_path):
    path = package / release.MANIFEST
    data = json.loads(path.read_text(encoding="utf-8"))
    data["name"] = "agent-workflow-frontier"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="包名"):
        release.install(package, tmp_path / "skills")


def test_source_cli_can_build_and_run_plan_from_unrelated_directory(tmp_path):
    destination = tmp_path / "source-cli-package"
    _assert_ok(_run(Path(release.__file__).resolve(), tmp_path, "build", "--output", destination))
    _assert_ok(_run(Path(release.__file__).resolve(), tmp_path, "verify", destination))
    release.install(destination, tmp_path / "skills")
    result = _assert_ok(_run(Path(release.__file__).resolve(), tmp_path, "update-plan", destination,
                             "--skills-root", tmp_path / "skills"))
    assert "unchanged" in result.stdout
