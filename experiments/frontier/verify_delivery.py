"""只读复核实验隔离和交付文件指纹，不替代行为测试或验收。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = Path(__file__).resolve().parent
MAIN = ROOT.parent.parent
INSTALLED = Path("/Users/yizhoucp/.codex/skills/agent-workflow")
BASELINE = "31989c7b909529f0f36d04558bba657f9b913c2f"
ALLOWED = ("experiments/", ".agent-workflow/30-records/work-items/W-20261009-frontier-workflow/")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(root, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(root)] + list(arguments),
        env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"),
    )


def audit():
    previous = json.loads((EXPERIMENT / "evidence/isolation-final.json").read_text())
    errors, stable, installed, sources = [], [], [], []
    for row in previous["stable_source"]["file_comparisons"]:
        relative = row["path"]
        baseline = hashlib.sha256(git(ROOT, "show", BASELINE + ":" + relative)).hexdigest()
        item = {"path": relative, "baseline_sha256": baseline,
                "experiment_sha256": sha(ROOT / relative), "main_sha256": sha(MAIN / relative)}
        item["passed"] = item["experiment_sha256"] == item["main_sha256"] == baseline
        stable.append(item)
        if not item["passed"]:
            errors.append("稳定文件改变：" + relative)
    for path in sorted((MAIN / "agent-workflow").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name == ".DS_Store":
            continue
        relative = path.relative_to(MAIN / "agent-workflow")
        target = INSTALLED / relative
        item = {"path": str(relative), "source_sha256": sha(path),
                "installed_sha256": sha(target) if target.is_file() else None}
        item["passed"] = item["source_sha256"] == item["installed_sha256"]
        installed.append(item)
        if not item["passed"]:
            errors.append("安装版与稳定源码不同：" + str(relative))
    source_names = {row["path"] for row in installed}
    installed_names = {str(path.relative_to(INSTALLED)) for path in INSTALLED.rglob("*")
                       if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store"}
    if installed_names != source_names:
        errors.append("安装版与稳定源码文件集合不同")
    fixture = json.loads((EXPERIMENT / "fixtures/p4/fixture-manifest.json").read_text())
    perturbations = {row["path"]: row["derived_sha256"] for row in fixture["perturbations"]}
    for node in fixture["nodes"].values():
        for row in node["files"]:
            item = {"original": row["original"], "copy": row["copy"],
                    "original_unchanged": sha(row["original"]) == row["sha256"],
                    "copy_matches_frozen_fixture": sha(row["copy"]) == perturbations.get(row["copy"], row["sha256"])}
            sources.append(item)
            if not item["original_unchanged"] or not item["copy_matches_frozen_fixture"]:
                errors.append("P4 来源或固定副本改变：" + row["copy"])
    main_status = git(MAIN, "status", "--porcelain=v1", "-z", "--untracked-files=all").decode()
    experiment_status = git(ROOT, "status", "--porcelain=v1", "-z", "--untracked-files=all").decode()
    entries = [entry for entry in experiment_status.split("\0") if entry]
    if main_status:
        errors.append("主工作区不干净")
    if any(not entry.startswith("?? ") or not entry[3:].startswith(ALLOWED) for entry in entries):
        errors.append("实验改动超出约定范围")
    if git(MAIN, "rev-parse", "HEAD").decode().strip() != BASELINE:
        errors.append("主工作区 HEAD 与基线不同")
    maintenance, artifacts = [], []
    for path in sorted(EXPERIMENT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        relative = str(path.relative_to(ROOT))
        artifacts.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha(path)})
        if path.parent == EXPERIMENT and path.suffix in (".py", ".md"):
            maintenance.append(relative)
            content = path.read_text(encoding="utf-8")
            if content and not content.endswith("\n"):
                errors.append("维护文件缺少末尾换行：" + relative)
            if any(line.rstrip() != line for line in content.splitlines()):
                errors.append("维护文件有行尾空白：" + relative)
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "只读隔离与文件指纹复核；不是测试通过证明",
        "baseline": BASELINE, "branch": git(ROOT, "branch", "--show-current").decode().strip(),
        "main_clean": not main_status, "changes_in_scope": not any(
            not e.startswith("?? ") or not e[3:].startswith(ALLOWED) for e in entries),
        "stable_files": stable, "installed_files": installed, "original_sources": sources,
        "maintenance_files_checked": maintenance, "artifacts": artifacts,
        "errors": errors, "passed": not errors,
        "notes": ["原始输出、历史失败 XML、输入与模型输出不做空白格式重写", "输出自身在写入前尚不存在，不包含自身哈希"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="新的 JSON 证据路径，拒绝覆盖")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("证据文件已存在，拒绝覆盖")
    result = audit()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "errors": result["errors"],
                      "stable_files": len(result["stable_files"]), "installed_files": len(result["installed_files"]),
                      "artifacts": len(result["artifacts"]), "output": str(args.output)}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
