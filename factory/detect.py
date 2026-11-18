"""Detect project stack, compose file and runnable components (port of detect.js)."""
from __future__ import annotations

import json
import os
import re

SKIP_CHILD_DIRS = {
    "node_modules", "dist", "build", "coverage", ".factory", ".factory",
    "plugins", "examples", "tests", "test", "bin", "venv", "__pycache__",
}
CONTAINER_DIRS = {"apps", "packages", "services", "libs", "modules"}
COMPOSE_FILES = ["docker-compose.yml", "compose.yaml", "docker-compose.yaml", "compose.yml"]


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _node_pm(abs_dir: str, root: str, pkg: dict) -> str:
    spec = pkg.get("packageManager") if isinstance(pkg, dict) else None
    if isinstance(spec, str):
        s = spec.strip().lower()
        for pm in ("pnpm", "yarn", "bun", "npm"):
            if s == pm or s.startswith(pm + "@"):
                return pm
    for d in ([abs_dir] if abs_dir == root else [abs_dir, root]):
        has = lambda n: os.path.exists(os.path.join(d, n))  # noqa: E731
        if has("pnpm-lock.yaml"):
            return "pnpm"
        if has("yarn.lock"):
            return "yarn"
        if has("bun.lockb") or has("bun.lock"):
            return "bun"
        if has("package-lock.json"):
            return "npm"
    return "npm"


def _inspect(dir_path: str, root: str) -> list[dict]:
    out: list[dict] = []
    abs_dir = os.path.abspath(dir_path)
    rel = "." if abs_dir == root else os.path.relpath(abs_dir, root).replace(os.sep, "/")
    default_name = (os.path.basename(root) or "root") if abs_dir == root else os.path.basename(abs_dir)
    isf = lambda n: os.path.isfile(os.path.join(abs_dir, n))  # noqa: E731

    if isf("package.json"):
        pkg = _read_json(os.path.join(abs_dir, "package.json"))
        if not isinstance(pkg, dict):
            pkg = {}
        pm = _node_pm(abs_dir, root, pkg)
        raw = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
        scripts = {k: v for k, v in raw.items() if isinstance(v, str)}
        cmds: dict[str, str] = {}
        if scripts.get("lint"):
            cmds["lint"] = f"{pm} run lint"
        if scripts.get("typecheck"):
            cmds["typecheck"] = f"{pm} run typecheck"
        elif scripts.get("type-check"):
            cmds["typecheck"] = f"{pm} run type-check"
        if scripts.get("test") and "Error: no test specified" not in scripts["test"]:
            cmds["test"] = "yarn test" if pm == "yarn" else f"{pm} test"
        if scripts.get("build"):
            cmds["build"] = f"{pm} run build"
        name = pkg.get("name").strip() if isinstance(pkg.get("name"), str) and pkg["name"].strip() else default_name
        out.append({"name": name, "path": abs_dir, "relPath": rel, "type": "node",
                    "packageManager": pm, "scripts": scripts, "commands": cmds})

    if isf("pyproject.toml") or isf("requirements.txt") or isf("setup.py"):
        text = "\n".join(_read(os.path.join(abs_dir, n)) if isf(n) else ""
                         for n in ("pyproject.toml", "requirements.txt", "setup.py"))
        cmds = {}
        if re.search(r"\bruff\b", text, re.I):
            cmds["lint"] = "ruff check ."
        if re.search(r"\bmypy\b", text, re.I):
            cmds["typecheck"] = "mypy ."
        if re.search(r"\bpytest\b", text, re.I):
            cmds["test"] = "python3 -m pytest"
        elif os.path.exists(os.path.join(abs_dir, "tests")):
            cmds["test"] = 'python3 -m unittest discover -s tests -p "test*.py"'
        out.append({"name": default_name, "path": abs_dir, "relPath": rel, "type": "python",
                    "scripts": {}, "commands": cmds})

    if isf("go.mod"):
        out.append({"name": default_name, "path": abs_dir, "relPath": rel, "type": "go", "scripts": {},
                    "commands": {"test": "go test ./...", "build": "go build ./..."}})
    if isf("Cargo.toml"):
        out.append({"name": default_name, "path": abs_dir, "relPath": rel, "type": "rust", "scripts": {},
                    "commands": {"test": "cargo test", "build": "cargo build"}})
    return out


def _child_dirs(path: str) -> list[str]:
    try:
        names = os.listdir(path)
    except OSError:
        return []
    return sorted(
        n for n in names
        if os.path.isdir(os.path.join(path, n)) and not os.path.islink(os.path.join(path, n))
        and not n.startswith(".") and n not in SKIP_CHILD_DIRS
    )


def detect_project(root: str) -> dict:
    root = os.path.abspath(root)
    compose = next((c for c in COMPOSE_FILES if os.path.isfile(os.path.join(root, c))), None)
    components: list[dict] = []
    if os.path.isdir(root):
        components.extend(_inspect(root, root))
        for child in _child_dirs(root):
            child_path = os.path.join(root, child)
            found = _inspect(child_path, root)
            components.extend(found)
            if child in CONTAINER_DIRS and not found:
                for nested in _child_dirs(child_path):
                    components.extend(_inspect(os.path.join(child_path, nested), root))
    return {"root": root, "hasDockerCompose": compose is not None,
            "dockerComposeFile": compose, "components": components}
