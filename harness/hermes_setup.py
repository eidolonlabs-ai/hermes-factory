"""`harness setup`: wire the installed engine into Hermes. Idempotent; re-run after upgrading.

  1. skills  -> $HERMES_HOME/skills/software-factory/{harness,harness-worker}
  2. profiles (definitions in profiles/<name>/): created by cloning the active profile, so they
     work at once with your model and keys; then given the role SOUL.md and the skills
  3. plugin  -> <profile>/plugins/harness, enabled (profiles with "plugin": true)

The plugin replaces the shell-hook block older installs appended to the coder's config.yaml;
that marked block is removed here. Your default profile's config is never modified.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .resources import data_dir

SKILL_CATEGORY = "software-factory"
PLUGIN_NAME = "harness"
SOUL_MARK = "<!-- hermes-agent-harness profile: {name} -->"
_LEGACY_HOOKS = re.compile(
    r"\n?# >>> hermes-agent-harness hooks\n.*?# <<< hermes-agent-harness hooks\n?", re.S)
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def hermes_home(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def profiles_root(home: Path) -> Path:
    """Named profiles live under the root home even when a profile is the active home."""
    root = home.parent.parent if home.parent.name == "profiles" else home
    return root / "profiles"


def _hermes(*args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["hermes", *args], capture_output=True, text=True, timeout=300,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def _live_runs() -> list[str]:
    """Run ids of live Hermes-engine runs (the guard must not be reloaded under them)."""
    from . import state
    out = []
    for f in sorted((state.home() / "active").glob("*.json")):
        try:
            e = json.loads(f.read_text())
            os.kill(int(e["pid"]), 0)
            out.append(str(e.get("run_id", f.stem)))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


class _Run:
    def __init__(self, dry: bool):
        self.dry, self.actions, self.warnings = dry, [], []

    def act(self, what: str, fn=None) -> None:
        self.actions.append(("would " if self.dry else "") + what)
        if fn is not None and not self.dry:
            fn()

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _copy_skills(run: _Run, skills_src: Path, home: Path) -> None:
    dest_root = home / "skills" / SKILL_CATEGORY
    for s in sorted(p for p in skills_src.iterdir() if (p / "SKILL.md").is_file()):
        dest = dest_root / s.name
        run.act(f"copy skill {s.name} -> {dest}",
                lambda s=s, dest=dest: shutil.copytree(s, dest, dirs_exist_ok=True, ignore=_IGNORE))


def _write_soul(run: _Run, src: Path, pdir: Path, name: str) -> None:
    dst, text = pdir / "SOUL.md", src.read_text(encoding="utf-8")
    old = dst.read_text(encoding="utf-8") if dst.is_file() else None
    if old == text:
        return

    def write():
        backup = pdir / "SOUL.md.pre-harness"
        if old is not None and SOUL_MARK.format(name=name) not in old and not backup.exists():
            backup.write_text(old, encoding="utf-8")
        dst.write_text(text, encoding="utf-8")
    run.act(f"write {dst}", write)


def _install_plugin(run: _Run, plugin_src: Path, pdir: Path, name: str) -> None:
    dest = pdir / "plugins" / PLUGIN_NAME

    def copy():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(plugin_src, dest, ignore=_IGNORE)
    run.act(f"install plugin -> {dest}", copy)

    def enable():
        # disable + enable: a running gateway re-imports the plugin, so new code takes effect now
        _hermes("-p", name, "plugins", "disable", PLUGIN_NAME)
        code, text = _hermes("-p", name, "plugins", "enable", PLUGIN_NAME, "--no-allow-tool-override")
        if code != 0:
            run.warn(f"could not enable plugin in {name}: {text[-300:]} "
                     f"(run: hermes -p {name} plugins enable {PLUGIN_NAME})")
    run.act(f"enable plugin {PLUGIN_NAME} in profile {name} (reloads it)", enable)

    cfg = pdir / "config.yaml"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        if _LEGACY_HOOKS.search(text):
            run.act(f"remove legacy shell-hook block from {cfg}",
                    lambda: cfg.write_text(_LEGACY_HOOKS.sub("\n", text), encoding="utf-8"))


def _setup_profile(run: _Run, pdef: Path, proot: Path, skills_src: Path, plugin_src: Path) -> None:
    name = pdef.name
    try:
        spec = json.loads((pdef / "profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        run.warn(f"profile {name}: bad profile.json ({e})")
        return
    pdir = proot / name
    if not pdir.is_dir():
        def create():
            code, text = _hermes("profile", "create", name, "--clone", "--no-alias",
                                 "--description", spec.get("description", ""))
            if code != 0:
                run.warn(f"could not create profile {name}: {text[-300:]}")
        run.act(f"create profile {name} (clone of the active profile)", create)
        if not run.dry and not pdir.is_dir():
            return
    if (pdef / "SOUL.md").is_file():
        _write_soul(run, pdef / "SOUL.md", pdir, name)
    _copy_skills(run, skills_src, pdir)
    if spec.get("plugin"):
        _install_plugin(run, plugin_src, pdir, name)


def run_setup(dry_run: bool = False, with_profiles: bool = True) -> dict:
    run = _Run(dry_run)
    home = hermes_home()
    plugin_src, profiles_src = data_dir("plugin"), data_dir("profiles")
    skills_src = plugin_src / "skills"
    if not skills_src.is_dir():
        return {"ok": False, "error": f"bundled Hermes files not found at {plugin_src}"}
    live = _live_runs()
    if live and not dry_run:
        return {"ok": False, "error": "harness runs are active (" + ", ".join(live) + "); setup reloads "
                "the guard plugin, so wait for them to finish or stop them first"}
    if not shutil.which("harness-hook"):
        run.warn("`harness-hook` is not on PATH; the guard will block every tool call of a "
                 "harness-coder run until it is (add ~/.local/bin to PATH)")
    _copy_skills(run, skills_src, home)
    if not shutil.which("hermes"):
        run.warn("hermes CLI not found: skipped profiles and plugin (claude/codex engines still work)")
    elif with_profiles and profiles_src.is_dir():
        proot = profiles_root(home)
        for pdef in sorted(p for p in profiles_src.iterdir() if (p / "profile.json").is_file()):
            _setup_profile(run, pdef, proot, skills_src, plugin_src)
    return {"ok": True, "dry_run": dry_run, "hermes_home": str(home),
            "actions": run.actions, "warnings": run.warnings, "next": "harness doctor"}
