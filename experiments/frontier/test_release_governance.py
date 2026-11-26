"""版本来源、发行信息与历史包兼容；写入仅限临时目录。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from experiments.frontier import build_release as release


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    shutil.copytree(release.REPOSITORY / "agent-workflow", root / "agent-workflow", ignore=ignore)
    frontier = root / "experiments/frontier"
    frontier.mkdir(parents=True)
    for path in (release.REPOSITORY / "experiments/frontier").glob("*.py"):
        if not path.name.startswith("test_"):
            shutil.copyfile(path, frontier / path.name)
    shutil.copytree(release.REPOSITORY / "experiments/frontier/skill", frontier / "skill", ignore=ignore)
    (root / "VERSION").write_text("9.2.3-beta.4\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# 变更记录\n\n## 未发布\n\n- 本次实际变化。\n\n## 旧版\n\n旧记录保持原样。\n", encoding="utf-8")
    return root


def _reseal(package, version):
    (package / release.MANIFEST).write_bytes(release._canonical(release._manifest(package, version)))


def test_selected_repository_is_only_version_source_and_package_is_independent(repository, tmp_path):
    package = tmp_path / "package"
    result = release.build(package, repository)
    assert result["version"] == "9.2.3-beta.4"
    assert result["channel"] == "preview"
    assert result["workflow_version"] == 6
    assert result["source"]["commit"] is None and result["source"]["dirty"] is None
    assert (package / "VERSION").read_text() == "9.2.3-beta.4\n"
    notes = (package / release.RELEASE_NOTES).read_text(encoding="utf-8")
    assert notes.startswith("# agent-workflow 9.2.3-beta.4\n")
    assert "本次实际变化" in notes and "旧记录" not in notes
    # 原源码已经不存在，包内校验仍然可运行，不读取构建器所在仓库的 VERSION。
    repository.rename(tmp_path / "hidden-source")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run([sys.executable, "-B", str(package / "scripts/release_package.py"), "verify", str(package)],
                               cwd=tmp_path, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert "9.2.3-beta.4" in completed.stdout


@pytest.mark.parametrize("value", [None, "", "01.1.0", "1.1.0-beta.01", "1.1.0\n1.2.0"])
def test_invalid_or_missing_version_does_not_create_output(repository, tmp_path, value):
    path = repository / "VERSION"
    if value is None:
        path.unlink()
    else:
        path.write_text(value, encoding="utf-8")
    output = tmp_path / "absent"
    with pytest.raises(ValueError):
        release.build(output, repository)
    assert not output.exists()


def test_changelog_and_tag_must_match_current_version(repository, tmp_path):
    with pytest.raises(ValueError, match="标签"):
        release.build(tmp_path / "absent", repository, expected_tag="v1.0.0")
    (repository / "CHANGELOG.md").write_text("# 变更记录\n\n## 1.0.0 - 2026-01-01\n\n旧说明\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CHANGELOG"):
        release.check_release(repository)
    assert not (tmp_path / "absent").exists()


def test_check_accepts_dated_release_notes_without_rewriting_history(repository):
    path = repository / "CHANGELOG.md"
    path.write_text(path.read_text(encoding="utf-8").replace("## 未发布", "## 9.2.3-beta.4 - 2026-11-25"), encoding="utf-8")
    before = path.read_bytes()
    assert release.check_release(repository, expected_tag="v9.2.3-beta.4")["status"] == "checked"
    assert path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["version", "channel", "workflow", "digest", "notes"])
def test_resealed_but_inconsistent_release_information_is_rejected(repository, tmp_path, mutation):
    package = tmp_path / "package"
    release.build(package, repository)
    info = json.loads((package / release.RELEASE_INFO).read_text())
    if mutation == "version":
        (package / "VERSION").write_text("99.0.0\n")
    elif mutation == "channel":
        info["channel"] = "stable"
    elif mutation == "workflow":
        info["workflow_version"] = 7
    elif mutation == "digest":
        info["source"]["content_sha256"] = "0" * 64
    else:
        (package / release.RELEASE_NOTES).write_text("# 错误版本\n")
        info["source"]["content_sha256"] = release._payload_digest(release._manifest(package, "9.2.3-beta.4"))
    (package / release.RELEASE_INFO).write_bytes(release._canonical(info))
    _reseal(package, "9.2.3-beta.4")
    with pytest.raises(ValueError):
        release.verify(package)


def test_new_verifier_accepts_historical_manifest_without_new_metadata(repository, tmp_path):
    package = tmp_path / "package"
    release.build(package, repository)
    for name in ("VERSION", release.RELEASE_INFO, release.RELEASE_NOTES):
        (package / name).unlink()
    _reseal(package, "1.1.0-beta.1")
    assert release.verify(package)["version"] == "1.1.0-beta.1"
    completed = subprocess.run([sys.executable, "-B", str(package / "scripts/release_package.py"), "verify", str(package)],
                               cwd=tmp_path, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_clean_source_gate_refuses_unknown_or_dirty_source(repository):
    with pytest.raises(ValueError, match="已提交"):
        release.check_release(repository, require_clean=True)
    def git(*args):
        subprocess.run(["git", "-C", str(repository), "-c", "user.name=Release Test", "-c", "user.email=test@example.invalid",
                        "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)
    git("init")
    git("add", "VERSION", "CHANGELOG.md", "agent-workflow", "experiments")
    git("commit", "-m", "test fixture")
    assert release.check_release(repository, require_clean=True)["source"]["dirty"] is False
    (repository / "untracked.txt").write_text("尚未提交")
    with pytest.raises(ValueError, match="干净"):
        release.check_release(repository, require_clean=True)


def test_build_rechecks_version_before_publishing(repository, tmp_path, monkeypatch):
    original = release._disable_bytecode
    def change_version(root):
        original(root)
        (repository / "VERSION").write_text("9.2.4\n")
    monkeypatch.setattr(release, "_disable_bytecode", change_version)
    output = tmp_path / "not-published"
    with pytest.raises(ValueError, match="构建期间"):
        release.build(output, repository)
    assert not output.exists()
