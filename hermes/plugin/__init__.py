"""Hermes plugin for hermes-agent-harness.

Thin on purpose: it never imports the engine. The guard decision is made by the
`harness-hook` executable (the same adapter the Claude Code hook uses), so this folder can be
installed on its own (`hermes plugins install owner/repo/hermes/plugin`) and the engine can be
upgraded independently.

Registers:
  pre_tool_call  guard; blocks on deny, on any error, and when the engine is missing
  pre_verify     one nudge per turn to run the milestone's verify script before finishing
  skills         harness:harness, harness:harness-worker

The guard is active in the `harness-coder` profile and in any session started by a harness run
(HARNESS_ROOT / HARNESS_FROZEN_FILE in the environment). Elsewhere it does nothing, so
enabling the plugin in your everyday profile is safe.

Hermes usually runs sessions inside one shared gateway process that serves every profile. So
the profile is read per call from Hermes (`ctx.profile_name`), not from this process's
environment, and the run a call belongs to is found by `harness-hook` through the registry of
live runs (<HARNESS_HOME>/active/), not through HARNESS_* variables.

Debug: `touch ~/.hermes/harness/hook-debug` appends one line per call to hook-debug.log.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_DIR = Path(__file__).parent
GUARD_PROFILES = ("harness-coder",)
_RUN_ENV = ("HARNESS_ROOT", "HARNESS_FROZEN_FILE")
_TIMEOUT_S = 15
_INSTALL_HINT = ("install the engine: uv tool install "
                 "git+https://github.com/theRealMarkCastillo/hermes-harness")


def _block(message: str) -> dict:
    return {"action": "block", "message": f"harness guard: {message}"}


_CTX = None  # set by register(); gives the profile of the turn being served


def _harness_home(env) -> Path:
    h = env.get("HARNESS_HOME")
    return Path(h).expanduser() if h else Path.home() / ".hermes" / "harness"


def _profile_name(env) -> str:
    """Profile this call runs for. Asks Hermes first (correct inside a shared gateway)."""
    if _CTX is not None:
        try:
            name = _CTX.profile_name
            if isinstance(name, str) and name:
                return name
        except Exception:
            pass
    home = env.get("HERMES_HOME") or ""
    p = Path(home) if home else None
    return p.name if p is not None and p.parent.name == "profiles" else "default"


def guard_active(env=None) -> bool:
    env = os.environ if env is None else env
    return (env.get("HARNESS_GUARD") == "1" or any(env.get(k) for k in _RUN_ENV)
            or _profile_name(env) in GUARD_PROFILES)


def _live_runs(env) -> list[dict]:
    """Entries the runner wrote for live Hermes-engine runs (pid still alive)."""
    out = []
    try:
        for f in sorted((_harness_home(env) / "active").glob("*.json")):
            try:
                e = json.loads(f.read_text(encoding="utf-8"))
                os.kill(int(e["pid"]), 0)
                out.append(e)
            except (OSError, ValueError, KeyError, TypeError):
                continue
    except OSError:
        pass
    return out


def _milestone(env) -> str:
    """Milestone of the run this session belongs to: env, else the live run at the session cwd,
    else the only live run."""
    if env.get("HARNESS_MILESTONE"):
        return env["HARNESS_MILESTONE"]
    runs = _live_runs(env)
    try:
        cwd = os.path.realpath(_cwd())
        here = [r for r in runs if cwd == os.path.realpath(str(r.get("root", "")))
                or cwd.startswith(os.path.realpath(str(r.get("root", ""))) + os.sep)]
    except Exception:
        here = []
    pick = here or (runs if len(runs) == 1 else [])
    return str(pick[0].get("milestone", "")) if pick else ""


def _debug(env, **fields) -> None:
    try:
        home = _harness_home(env)
        if (home / "hook-debug").exists():
            with open(home / "hook-debug.log", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"kind": "plugin", "pid": os.getpid(), **fields}, default=str) + "\n")
    except Exception:
        pass


def _hook_bin(env) -> str | None:
    explicit = env.get("HARNESS_HOOK_BIN")
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("harness-hook", path=env.get("PATH"))
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "harness-hook"
    return str(fallback) if os.access(fallback, os.X_OK) else None


def _cwd() -> str:
    try:
        from agent.runtime_cwd import resolve_agent_cwd  # Hermes' session cwd, when available
        return str(resolve_agent_cwd())
    except Exception:
        return os.getcwd()


def guard(tool_name: str = "", args: dict | None = None, **_kwargs):
    """pre_tool_call. Fails closed: every path that cannot produce a decision blocks."""
    try:
        env = os.environ
        active = guard_active(env)
        _debug(env, tool=tool_name, profile=_profile_name(env), active=active)
        if not active:
            return None
        exe = _hook_bin(env)
        if not exe:
            return _block(f"`harness-hook` not found on PATH; {_INSTALL_HINT}")
        payload = {"hook_event_name": "pre_tool_call", "tool_name": tool_name,
                   "tool_input": args if isinstance(args, dict) else {}, "cwd": _cwd()}
        proc = subprocess.run([exe, "hermes"], input=json.dumps(payload, default=str),
                              capture_output=True, text=True, timeout=_TIMEOUT_S, env=dict(env))
        if proc.returncode != 0:
            return _block(f"harness-hook exited {proc.returncode}: {proc.stderr.strip()[-300:]}")
        out = json.loads(proc.stdout.strip() or "{}")
        if not isinstance(out, dict):
            return _block("harness-hook returned a non-object")
        action = out.get("action")
        if action in ("block", "approve"):
            return {"action": action, "message": str(out.get("message") or "blocked by harness guard")}
        if action:
            return _block(f"unknown action {action!r}")
        return None
    except BaseException as exc:  # noqa: BLE001 - a guard that raises would be skipped (fail open)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return _block(f"guard error: {type(exc).__name__}: {exc}")


def verify_nudge(coding: bool = True, attempt: int = 0, **_kwargs):
    """pre_verify. Never runs the gate: the harness gate, outside the agent, is the authority."""
    try:
        env = os.environ
        if attempt or not coding or not guard_active(env):
            return None
        milestone = _milestone(env)
        if not milestone or milestone == "M0":
            return None
        return {"action": "continue",
                "message": (f"Before finishing: run `scripts/verify.sh {milestone}` (logs to files, read "
                            "the tail), fix any failure at the root cause, commit, then finish. Do not "
                            "edit frozen files or weaken tests. The external gate will re-run everything.")}
    except Exception:
        return None


def register(ctx) -> None:
    global _CTX
    _CTX = ctx
    ctx.register_hook("pre_tool_call", guard)
    ctx.register_hook("pre_verify", verify_nudge)
    skills = _DIR / "skills"
    if skills.is_dir():
        for child in sorted(skills.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
