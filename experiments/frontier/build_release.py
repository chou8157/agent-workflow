"""构建、校验、安装和连续更新 agent-workflow；更新前生成绑定当前内容的计划。"""

from __future__ import annotations

import argparse
import ast
import ctypes
import errno
import gzip
import hashlib
import io
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tarfile
import tempfile


PACKAGE_NAME = "agent-workflow"
VERSION = "1.1.0-beta.1"
MANIFEST = "release-manifest.json"
REPOSITORY = Path(__file__).resolve().parents[2]
RUNTIME_MODULES = (
    "light_cli", "light_report", "mvp_light", "activity_closeout", "node_workflow",
    "coordinator", "storage_common", "file_store", "sqlite_store", "log_store", "service_stores", "bounded_node_query",
)
REQUIRED_FILES = {
    "SKILL.md", "references/local-workflow.md", "references/network-mode.md",
    "agents/openai.yaml", "scripts/task_context.py", "scripts/scaffold_workflow.py",
    "scripts/release_package.py",
} | {"scripts/frontier/{}.py".format(name) for name in RUNTIME_MODULES}


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _path(value):
    candidate = Path(value).expanduser().absolute()
    if candidate.is_symlink():
        raise ValueError("拒绝符号链接路径：{}".format(candidate))
    return candidate.resolve()


def _inventory(root):
    root = _path(root)
    if not root.is_dir():
        raise ValueError("交付包目录不存在：{}".format(root))
    files, directories = {}, []
    for parent, names, filenames in os.walk(root, followlinks=False):
        for name in sorted(names + filenames):
            path = Path(parent) / name
            mode = path.lstat().st_mode
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(mode):
                raise ValueError("交付包不能包含符号链接：{}".format(relative))
            if stat.S_ISDIR(mode):
                directories.append(relative)
            elif stat.S_ISREG(mode):
                if relative != MANIFEST:
                    raw = path.read_bytes()
                    files[relative] = {"sha256": _digest(raw), "size": len(raw)}
            else:
                raise ValueError("交付包只允许普通文件和目录：{}".format(relative))
    return dict(sorted(files.items())), sorted(directories)


def _manifest(root, version=None):
    files, directories = _inventory(root)
    return {"schema_version": 1, "name": PACKAGE_NAME, "version": version or VERSION,
            "files": files, "directories": directories}


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("manifest 包含无效相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise ValueError("manifest 包含不安全相对路径：{}".format(value))


def _skill_name(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("SKILL.md 缺少 frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError("SKILL.md frontmatter 未闭合") from error
    names = [line.split(":", 1)[1].strip().strip("\"'") for line in lines[1:end]
             if line.startswith("name:")]
    if names != [PACKAGE_NAME]:
        raise ValueError("SKILL.md 名称必须是 {}".format(PACKAGE_NAME))


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?", value):
        raise ValueError("产品版本不是受支持的语义版本：{}".format(value))
    base, _, prerelease = value.split("+", 1)[0].partition("-")
    parts = prerelease.split(".") if prerelease else []
    if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in parts):
        raise ValueError("产品预发布版本不能包含有前导零的数字")
    return tuple(map(int, base.split("."))), tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)


def compare_versions(left, right):
    left_base, left_pre = _version(left)
    right_base, right_pre = _version(right)
    if left_base != right_base:
        return (left_base > right_base) - (left_base < right_base)
    if not left_pre or not right_pre:
        return bool(right_pre) - bool(left_pre)
    return (left_pre > right_pre) - (left_pre < right_pre)


def verify(package):
    """核实完整文件集合及哈希；manifest 是完整性清单，不是来源签名。"""
    package = _path(package)
    manifest_path = package / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("交付包缺少普通文件 manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("manifest 无法读取或格式无效") from error
    if (not isinstance(manifest, dict) or
            set(manifest) != {"schema_version", "name", "version", "files", "directories"} or
            type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["name"] != PACKAGE_NAME or
            not isinstance(manifest["files"], dict) or not isinstance(manifest["directories"], list)):
        raise ValueError("manifest 的包名、版本或结构不受支持")
    _version(manifest["version"])
    for relative, metadata in manifest["files"].items():
        _relative(relative)
        if (relative == MANIFEST or not isinstance(metadata, dict) or set(metadata) != {"sha256", "size"} or
                not isinstance(metadata["sha256"], str) or len(metadata["sha256"]) != 64 or
                any(char not in "0123456789abcdef" for char in metadata["sha256"]) or
                type(metadata["size"]) is not int or metadata["size"] < 0):
            raise ValueError("manifest 文件摘要无效：{}".format(relative))
    for relative in manifest["directories"]:
        _relative(relative)
    if "SKILL.md" not in manifest["files"]:
        raise ValueError("交付包缺少 SKILL.md")
    actual = _manifest(package, manifest["version"])
    if actual != manifest:
        missing = sorted(set(manifest["files"]) - set(actual["files"]))
        extra = sorted(set(actual["files"]) - set(manifest["files"]))
        changed = sorted(name for name in set(actual["files"]) & set(manifest["files"])
                         if actual["files"][name] != manifest["files"][name])
        raise ValueError("交付包校验失败：缺少={}；多余={}；变化={}；目录一致={}".format(
            missing, extra, changed, actual["directories"] == manifest["directories"]))
    _skill_name(package / "SKILL.md")
    return manifest


def _copy_source(source, destination):
    if source.is_symlink():
        raise ValueError("构建来源不能包含符号链接：{}".format(source))
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir()):
            if (child.name in ("__pycache__", ".pytest_cache", "tests", ".DS_Store") or
                    child.name.startswith("test_") or child.suffix in (".pyc", ".pyo")):
                continue
            _copy_source(child, destination / child.name)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    else:
        raise ValueError("构建来源不存在或不是普通文件：{}".format(source))


def _check_runtime_dependencies(frontier):
    available = {path.stem for path in frontier.glob("*.py")}
    included = set(RUNTIME_MODULES)
    for name in RUNTIME_MODULES:
        tree = ast.parse((frontier / (name + ".py")).read_text(encoding="utf-8"))
        dependencies = set()
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                dependencies.update(alias.name.split(".", 1)[0] for alias in item.names)
            elif isinstance(item, ast.ImportFrom):
                if item.module:
                    dependencies.add(item.module.split(".", 1)[0])
                elif item.level:
                    dependencies.update(alias.name for alias in item.names)
        missing = (dependencies & available) - included
        if missing:
            raise ValueError("运行时依赖遗漏：{} -> {}".format(name, ", ".join(sorted(missing))))


def _disable_bytecode(root):
    # 交付文件保持不变，使用后仍可严格核对完整文件清单。
    for path in (root / "scripts").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        body = ast.parse(source).body
        insert_at = 0
        for index, statement in enumerate(body):
            if ((index == 0 and isinstance(statement, ast.Expr) and
                 isinstance(statement.value, (ast.Str, ast.Constant))) or
                    (isinstance(statement, ast.ImportFrom) and statement.module == "__future__")):
                insert_at = statement.end_lineno
            else:
                break
        lines = source.splitlines(keepends=True)
        lines.insert(insert_at, "\nimport sys as _release_sys\n_release_sys.dont_write_bytecode = True\n")
        path.write_text("".join(lines), encoding="utf-8")


def _release_modes(root):
    # 与 tar 发行物一致，避免构建临时目录或调用者 umask 改变包身份。
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    root.chmod(0o755)


def _rename_new(source, destination):
    """使用系统的排他 rename，避免并发安装覆盖先到的目录。"""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(source), os.fsencode(destination), 4)
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise ValueError("当前系统不支持安全的排他安装；目前支持 macOS/Linux")
    if result:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError("目标目录已存在：{}".format(destination))
        raise OSError(code, os.strerror(code), str(destination))


def _same_destination(destination, manifest):
    if not destination.exists() and not destination.is_symlink():
        return False
    if verify(destination) != manifest:
        raise ValueError("目标目录已有不同交付包，拒绝覆盖：{}".format(destination))
    return True


def _publish(temporary, destination, manifest):
    if _same_destination(destination, manifest):
        return "unchanged"
    try:
        _rename_new(temporary, destination)
    except FileExistsError:
        if _same_destination(destination, manifest):
            return "unchanged"
        raise
    return "created"


def build(output, repository=None):
    repository = _path(repository or REPOSITORY)
    source = repository / "agent-workflow"
    frontier = repository / "experiments/frontier"
    overlay = frontier / "skill"
    for relative in ("SKILL.md", "references/network-mode.md", "agents/openai.yaml"):
        if not (overlay / relative).is_file():
            raise ValueError("发布入口尚未准备完整：{}".format(overlay / relative))
    _check_runtime_dependencies(frontier)
    output = _path(output)
    if output == repository or repository in output.parents:
        raise ValueError("交付包必须构建到开发仓库之外")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="." + PACKAGE_NAME + "-build-", dir=output.parent))
    try:
        for name in ("scripts", "assets", "references"):
            _copy_source(source / name, temporary / name)
        lines = (source / "SKILL.md").read_text(encoding="utf-8").splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise ValueError("原 SKILL.md 缺少 frontmatter，不能生成本地工作流说明")
        end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if end is None:
            raise ValueError("原 SKILL.md frontmatter 未闭合")
        (temporary / "references/local-workflow.md").write_text("".join(lines[end + 1:]).lstrip("\n"), encoding="utf-8")
        _copy_source(overlay, temporary)
        for name in RUNTIME_MODULES:
            _copy_source(frontier / (name + ".py"), temporary / "scripts/frontier" / (name + ".py"))
        _copy_source(Path(__file__), temporary / "scripts/release_package.py")
        _copy_source(frontier / "release_update.py", temporary / "scripts/release_update.py")
        _disable_bytecode(temporary)
        _release_modes(temporary)
        manifest = _manifest(temporary)
        if not REQUIRED_FILES | {"scripts/release_update.py"} <= manifest["files"].keys():
            raise ValueError("当前构建缺少必需的运行文件")
        (temporary / MANIFEST).write_bytes(_canonical(manifest))
        (temporary / MANIFEST).chmod(0o644)
        verify(temporary)
        status = _publish(temporary, output, manifest)
        return {"status": status, "path": str(output), "name": PACKAGE_NAME, "version": VERSION,
                "files": len(manifest["files"]), "manifest_sha256": _digest(_canonical(manifest))}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _install(package, skills_root):
    manifest = verify(package)
    package = _path(package)
    skills_root = _path(skills_root)
    destination = skills_root / PACKAGE_NAME
    if _same_destination(destination, manifest):
        return {"status": "unchanged", "path": str(destination)}
    skills_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="." + PACKAGE_NAME + "-install-", dir=skills_root))
    try:
        shutil.copytree(package, temporary, dirs_exist_ok=True, symlinks=True)
        if verify(temporary) != manifest:
            raise ValueError("复制期间来源发生变化，拒绝安装")
        status = _publish(temporary, destination, manifest)
        return {"status": status, "path": str(destination)}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _updater():
    if __package__:
        from . import release_update
    else:
        import release_update
    return release_update


def install(package, skills_root):
    verify(package)
    with _updater().installation_lock(skills_root, create=True):
        _updater().assert_no_pending(skills_root)
        return _install(package, skills_root)


def archive(package, destination):
    manifest = verify(package)
    package = _path(package)
    destination = _path(destination)
    if destination == package or package in destination.parents:
        raise ValueError("压缩包必须位于交付目录之外")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="." + PACKAGE_NAME + "-archive-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as bundle:
                    for relative in [""] + manifest["directories"] + sorted(list(manifest["files"]) + [MANIFEST]):
                        path = package / relative
                        info = bundle.gettarinfo(str(path), arcname=PACKAGE_NAME + ("/" + relative if relative else ""))
                        if not (info.isdir() or info.isreg()):
                            raise ValueError("压缩来源包含非普通文件")
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ""
                        info.mode = 0o755 if info.isdir() else 0o644
                        if info.isfile():
                            raw = path.read_bytes()
                            expected = (_canonical(manifest) if relative == MANIFEST else None)
                            if ((relative == MANIFEST and raw != expected) or
                                    (relative != MANIFEST and {"size": len(raw), "sha256": _digest(raw)} != manifest["files"][relative])):
                                raise ValueError("打包期间来源文件变化：{}".format(relative))
                            info.size = len(raw)
                            bundle.addfile(info, io.BytesIO(raw))
                        else:
                            bundle.addfile(info)
        if verify(package) != manifest:
            raise ValueError("打包期间来源发生变化，拒绝发布压缩包")
        try:
            os.link(temporary, destination)
            status = "created"
        except FileExistsError:
            if not destination.is_file() or destination.read_bytes() != temporary.read_bytes():
                raise ValueError("压缩目标已存在不同内容，拒绝覆盖")
            status = "unchanged"
        return {"status": status, "path": str(destination), "sha256": _digest(temporary.read_bytes())}
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="从实验工作区构建独立交付包")
    build_parser.add_argument("--output", type=Path, required=True, help="仓库之外的包目录；已有不同内容时拒绝覆盖")
    build_parser.add_argument("--archive", type=Path, help="可选 tar.gz 输出路径；已有不同内容时拒绝覆盖")
    verify_parser = commands.add_parser("verify", help="检查包名、版本、文件集合和全部哈希")
    verify_parser.add_argument("package", type=Path, help="已解压的交付包目录")
    install_parser = commands.add_parser("install", help="首次安装 agent-workflow；已有不同内容时请使用 update")
    install_parser.add_argument("package", type=Path, help="已校验交付包的目录")
    install_parser.add_argument("--skills-root", type=Path, required=True, help="目标 skills 根目录；没有隐含安装路径")
    updater = _updater()
    updater.add_commands(commands)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.output)
            if args.archive:
                result["archive"] = archive(args.output, args.archive)
        elif args.command == "verify":
            manifest = verify(args.package)
            result = {"status": "verified", "name": manifest["name"], "version": manifest["version"],
                      "files": len(manifest["files"])}
        elif args.command == "install":
            result = install(args.package, args.skills_root)
        else:
            result = updater.dispatch(args)
        sys.stdout.write("交付包操作完成：{}\n".format(json.dumps(result, ensure_ascii=False, sort_keys=True)))
        return 0
    except Exception as error:
        sys.stderr.write("交付包操作失败：{}\n".format(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
