#!/usr/bin/env python3
"""按需启用项目工作流能力模块。"""
from __future__ import annotations

import argparse, json, shutil
from pathlib import Path

WORKFLOW_DIR = ".agent-workflow"
STATE_FILE = ".capabilities.json"
CAPABILITIES = {
    "core": {"depends": [], "paths": ["00-core", "README.md", "WORKFLOW_VERSION"]},
    "work-items": {"depends": ["core"], "paths": ["30-records/work-items"]},
    "decisions": {"depends": ["core"], "paths": ["30-records/decisions"]},
    "contracts": {"depends": ["core"], "paths": ["10-project/contracts"]},
    "knowledge": {"depends": ["core"], "paths": ["10-project/knowledge"]},
    "evidence": {"depends": ["core"], "paths": ["30-records/evidence"]},
    "delivery": {"depends": ["evidence"], "paths": ["30-records/delivery"]},
    "shared-workflow": {"depends": ["core"], "paths": ["15-modules/shared-workflow"]},
    "audit": {"depends": ["evidence", "decisions"], "paths": ["20-gates/audit"]},
}
PROFILES = {
    "minimum": ["core", "work-items"],
    "standard": ["core", "work-items", "decisions", "knowledge", "evidence"],
    "advanced": ["core", "work-items", "decisions", "contracts", "knowledge", "evidence", "delivery", "audit", "shared-workflow"],
}

def closure(names: list[str]) -> list[str]:
    out: list[str] = []
    def add(name: str) -> None:
        if name not in CAPABILITIES:
            raise ValueError(f"未知能力：{name}")
        for dep in CAPABILITIES[name]["depends"]: add(dep)
        if name not in out: out.append(name)
    for name in names: add(name)
    return out

def state_path(project: Path) -> Path: return project / WORKFLOW_DIR / STATE_FILE

def read_state(project: Path) -> dict:
    path = state_path(project)
    if not path.exists(): return {"version": 1, "enabled": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("enabled", []), list): raise ValueError("能力清单格式无效")
    unknown = [x for x in data["enabled"] if x not in CAPABILITIES]
    if unknown: raise ValueError(f"能力清单包含未知能力：{', '.join(unknown)}")
    return data

def write_state(project: Path, enabled: list[str]) -> None:
    path = state_path(project); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "enabled": enabled}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def enable(project: Path, names: list[str], profile: str | None = None) -> list[str]:
    requested = list(names)
    if profile:
        if profile not in PROFILES: raise ValueError(f"未知 profile：{profile}")
        requested += PROFILES[profile]
    desired = closure(requested)
    current = read_state(project).get("enabled", [])
    enabled = closure(list(current) + desired)
    template = Path(__file__).resolve().parents[1] / "assets" / "templates" / WORKFLOW_DIR
    for cap in enabled:
        for rel in CAPABILITIES[cap]["paths"]:
            src, dst = template / rel, project / WORKFLOW_DIR / rel
            if src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file():
                        target = dst / f.relative_to(src); target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists(): shutil.copy2(f, target)
            elif src.is_file() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
            elif not dst.exists():
                dst.mkdir(parents=True, exist_ok=True)
    write_state(project, enabled)
    return [x for x in enabled if x not in current]

def suggest(project: Path) -> list[str]:
    root = project / WORKFLOW_DIR
    suggestions = []
    if (root / "30-records" / "delivery").exists() or any(root.rglob("*delivery*")): suggestions.append("delivery")
    if (root / "30-records" / "evidence").exists(): suggestions.append("evidence")
    if any(root.rglob("ADR-*.md")): suggestions.append("decisions")
    return list(dict.fromkeys(suggestions))

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("project", nargs="?", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("list", "suggest"): sub.add_parser(name)
    e = sub.add_parser("enable"); e.add_argument("capabilities", nargs="*"); e.add_argument("--profile", choices=sorted(PROFILES))
    args = p.parse_args(argv); project = Path(args.project).resolve()
    try:
        if args.cmd == "list": print(json.dumps(read_state(project), ensure_ascii=False, indent=2))
        elif args.cmd == "suggest": print(json.dumps({"suggestions": suggest(project)}, ensure_ascii=False))
        else:
            added = enable(project, args.capabilities, args.profile); print("已启用：" + ("、".join(added) if added else "无新增能力"))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as err:
        p.error(str(err)); return 2
if __name__ == "__main__": raise SystemExit(main())
