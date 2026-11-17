"""Thin stdin/stdout adapters wiring the guard into Hermes and Claude Code hooks.

Each entry point takes the raw stdin string and an env mapping and returns
(stdout_str, exit_code). Malformed input fails closed (block).
"""
from __future__ import annotations

import json
import os
import sys

from harness.guard import decide_tool_call
from harness.types import GuardContext


def _frozen(root: str, env) -> list[str]:
    """Frozen list: env HARNESS_FROZEN_FILE, else <root>/.harness/frozen.json, else []."""
    path = env.get("HARNESS_FROZEN_FILE") or os.path.join(root, ".harness", "frozen.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [str(x) for x in data] if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        if env.get("HARNESS_FROZEN_FILE"):
            raise  # explicitly configured but unreadable: fail closed in the caller
        return []


def _context(payload: dict, env) -> GuardContext:
    root = env.get("HARNESS_ROOT") or payload.get("cwd") or os.getcwd()
    return GuardContext(root=root, control_dir=".harness/", frozen=_frozen(root, env),
                        unattended=env.get("HARNESS_UNATTENDED", "1") != "0")


def _parse(raw: str) -> dict:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    return payload


def hermes_pre_tool_call(raw: str, env) -> tuple[str, int]:
    """Hermes shell-hook protocol: always exit 0, decision in the JSON body."""
    try:
        payload = _parse(raw)
        ctx = _context(payload, env)
        d = decide_tool_call(payload.get("tool_name", ""), payload.get("tool_input") or {}, ctx)
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
