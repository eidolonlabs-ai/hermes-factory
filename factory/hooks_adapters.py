"""Thin stdin/stdout adapters wiring the guard into Hermes and Claude Code hooks.

Each entry point takes the raw stdin string and an env mapping and returns
(stdout_str, exit_code). Malformed input fails closed (block).
"""
from __future__ import annotations

import json
import os
import sys

from factory.guard import decide_tool_call
from factory.types import GuardContext


def _frozen(root: str, env) -> list[str]:
    """Frozen list: env FACTORY_FROZEN_FILE, else <root>/.factory/frozen.json, else []."""
    explicit = env.get("FACTORY_FROZEN_FILE")
    path = explicit or os.path.join(root, ".factory", "frozen.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            if explicit:
                raise ValueError("FACTORY_FROZEN_FILE must contain a JSON list")
            return []
        return [str(x) for x in data]
    except FileNotFoundError:
        if explicit:
            raise  # explicitly configured but missing: fail closed in the caller
        return []
    except (OSError, ValueError):
        if explicit:
            raise  # explicitly configured but unreadable: fail closed in the caller
        return []


def _from_worktree(cwd: str) -> tuple[str, str] | None:
    """(worktree root, frozen.json path) when cwd is inside a factory worktree.

    Hermes runs shell hooks with a sanitised environment, so FACTORY_* variables set for the
    engine may not reach the hook. The worktree path itself identifies the run:
    <FACTORY_HOME>/worktrees/<project>/<run_id>/...  ->  <FACTORY_HOME>/runs/<project>/<run_id>/frozen.json
    """
    try:
        from . import state
        base = os.path.realpath(str(state.worktrees_dir("_")).rsplit("/", 1)[0])
    except Exception:
        return None
    real = os.path.realpath(cwd)
    if not real.startswith(base + os.sep):
        return None
    parts = real[len(base) + 1:].split(os.sep)
    if len(parts) < 2:
        return None
    project, run_id = parts[0], parts[1]
    return os.path.join(base, project, run_id), str(state.run_dir(project, run_id) / "frozen.json")


def _active_runs() -> list[dict]:
    """Live Hermes-engine runs registered by the runner (<FACTORY_HOME>/active/*.json).

    Needed because Hermes runs shell hooks from its profile home with a scrubbed environment:
    the hook cannot see FACTORY_* variables or the engine's working directory.
    """
    try:
        from . import state
        d = state.home() / "active"
        out = []
        for f in sorted(d.glob("*.json")):
            try:
                e = json.loads(f.read_text())
                os.kill(int(e["pid"]), 0)  # raises if the runner process is gone
                out.append(e)
            except (OSError, ValueError, KeyError):
                continue
        return out
    except Exception:
        return []


def _contexts(payload: dict, env) -> list[GuardContext]:
    """One context normally; one per active run when the hook cannot tell which run fired it."""
    cwd = payload.get("cwd") or os.getcwd()
    if env.get("FACTORY_FROZEN_FILE") or env.get("FACTORY_ROOT") or _from_worktree(cwd):
        return [_context(payload, env)]
    ctxs = []
    for e in _active_runs():
        ctxs.append(_context({**payload, "cwd": e["root"]},
                             {**env, "FACTORY_ROOT": e["root"], "FACTORY_FROZEN_FILE": e["frozen_file"],
                              "FACTORY_MILESTONE": e.get("milestone", "")}))
    return ctxs or [_context(payload, env)]


def _decide(payload: dict, env) -> tuple[Decision, GuardContext]:
    """Worst decision across contexts (deny > ask > allow)."""
    from .guard import SEVERITY
    worst, wctx = None, None
    for ctx in _contexts(payload, env):
        d = decide_tool_call(payload.get("tool_name", ""), payload.get("tool_input") or {}, ctx)
        if worst is None or SEVERITY[d.decision] > SEVERITY[worst.decision]:
            worst, wctx = d, ctx
    return worst, wctx


def _effective_cwd(payload: dict, root: str) -> str:
    """Resolve effective cwd for relative tool paths (supports Hermes terminal workdir)."""
    from .guard import SHELL_TOOLS
    p_cwd = payload.get("cwd")
    p_cwd = p_cwd if isinstance(p_cwd, str) and p_cwd.strip() else ""
    tool_name = str(payload.get("tool_name") or "").lower()
    inp = payload.get("tool_input")
    if tool_name in SHELL_TOOLS and isinstance(inp, dict):
        wd = inp.get("workdir") or inp.get("cwd")
        if isinstance(wd, str) and wd.strip():
            wd = wd.strip()
            return wd if os.path.isabs(wd) else os.path.join(p_cwd or root, wd)
    if p_cwd and root:
        r_real = os.path.realpath(root).rstrip(os.sep)
        c_real = os.path.realpath(p_cwd)
        if c_real == r_real or c_real.startswith(r_real + os.sep):
            return p_cwd
    return ""


def _context(payload: dict, env) -> GuardContext:
    cwd = payload.get("cwd") or os.getcwd()
    if not env.get("FACTORY_FROZEN_FILE"):
        found = _from_worktree(env.get("FACTORY_ROOT") or cwd)
        if found:
            env = {**env, "FACTORY_ROOT": env.get("FACTORY_ROOT") or found[0]}
            if os.path.exists(found[1]) or os.path.isdir(os.path.dirname(found[1])):
                env = {**env, "FACTORY_FROZEN_FILE": found[1]}
    root = env.get("FACTORY_ROOT") or cwd
    return GuardContext(root=root, control_dir=".factory/", frozen=_frozen(root, env),
                        contract_phase=env.get("FACTORY_MILESTONE") == "M0",
                        unattended=env.get("FACTORY_UNATTENDED", "1") != "0",
                        cwd=_effective_cwd(payload, root))


def _parse(raw: str) -> dict:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    return payload


def _debug_log(kind: str, payload: dict, env, ctx) -> None:
    """Opt-in trace: touch <FACTORY_HOME>/hook-debug to append one line per hook call."""
    try:
        from . import state
        flag = state.home() / "hook-debug"
        if flag.exists():
            with open(state.home() / "hook-debug.log", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"kind": kind, "cwd": payload.get("cwd"), "proc_cwd": os.getcwd(),
                                     "tool": payload.get("tool_name"), "root": ctx.root,
                                     "frozen": ctx.frozen, "env_root": env.get("FACTORY_ROOT"),
                                     "keys": sorted(payload), "input": payload.get("tool_input")}) + "\n")
    except Exception:
        pass


def hermes_pre_tool_call(raw: str, env) -> tuple[str, int]:
    """Hermes shell-hook protocol: always exit 0, decision in the JSON body."""
    try:
        payload = _parse(raw)
        d, ctx = _decide(payload, env)
        _debug_log("hermes", payload, env, ctx)
    except Exception as exc:
        return json.dumps({"action": "block", "message": f"guard error: {exc}"}), 0
    if d.decision == "deny":
        return json.dumps({"action": "block", "message": d.reason}), 0
    if d.decision == "ask":
        if ctx.unattended:
            return json.dumps({"action": "block", "message": f"needs human approval: {d.reason}"}), 0
        return json.dumps({"action": "approve", "message": d.reason}), 0
    return "{}", 0


def claude_pre_tool_use(raw: str, env) -> tuple[str, int]:
    """Claude Code PreToolUse: exit 2 + reason on stderr blocks the call.
    Returns (stdout, exit_code); the reason is also in the JSON body (stderr is written by main)."""
    try:
        payload = _parse(raw)
        ctx = _context(payload, env)
        d = decide_tool_call(payload.get("tool_name", ""), payload.get("tool_input") or {}, ctx)
    except Exception as exc:
        return _claude_block(f"guard error: {exc}"), 2
    if d.decision == "deny" or (d.decision == "ask" and ctx.unattended):
        reason = d.reason if d.decision == "deny" else f"needs human approval: {d.reason}"
        return _claude_block(reason), 2
    if d.decision == "ask":  # attended: let Claude Code prompt the human
        return json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask",
            "permissionDecisionReason": d.reason}}), 0
    return "", 0


def _claude_block(reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}})


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    which = argv[1] if len(argv) > 1 else ""
    fn = {"hermes": hermes_pre_tool_call, "claude": claude_pre_tool_use}.get(which)
    if fn is None:
        sys.stderr.write("usage: hooks_adapters.py hermes|claude\n")
        return 2
    out, code = fn(sys.stdin.read(), os.environ)
    if out:
        sys.stdout.write(out + "\n")
    if code == 2 and which == "claude":
        try:  # reason on stderr for Claude Code
            sys.stderr.write(json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] + "\n")
        except Exception:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
