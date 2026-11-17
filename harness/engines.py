"""Engine argv builders and probes (DESIGN §5). Argv lists only, never a shell."""
from __future__ import annotations

import json
import shlex
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .models import ENGINE_NAMES

CLAUDE_EMPTY_MCP = '{"mcpServers":{}}'
PKG_PARENT = str(Path(__file__).resolve().parent.parent)


@dataclass
class Invocation:
    argv: list
    env: dict
    stdin_text: str = ""
    last_message: Path | None = None
    extra: dict = field(default_factory=dict)


def other_vendor(engine: str) -> str:
    return {"codex": "claude", "claude": "codex", "hermes": "claude", "agy": "claude",
            "fake": "fake"}[engine]


def resolve_review_engine(cfg_value: str, builder: str) -> str:
    return other_vendor(builder) if cfg_value == "cross" else cfg_value


def probe(engine: str) -> tuple[bool, str]:
    if engine not in ENGINE_NAMES:
        return False, f"unknown engine {engine}"
    if engine == "fake":
        p = os.environ.get("HARNESS_FAKE_ENGINE")
        if p and Path(p).is_file():
            return True, p
        return False, "HARNESS_FAKE_ENGINE is not set to an existing script"
    exe = {"codex": "codex", "claude": "claude", "hermes": "hermes", "agy": "agy"}[engine]
    path = shutil.which(exe)
    return (True, path) if path else (False, f"{exe} not found on PATH")


def base_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
    for k in list(env):  # do not inherit a Hermes worker's board identity
        if k.startswith("HERMES_KANBAN"):
            env.pop(k)
    env["PYTHONPATH"] = PKG_PARENT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.update(extra or {})
    return env


def claude_settings(run_dir: Path) -> Path:
    """Per-run settings JSON: PreToolUse guard hook. Lives outside the repo."""
    settings = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": f"{shlex.quote(sys.executable)} -m harness.hooks_adapters claude"}]}]}}
    p = Path(run_dir) / "claude-settings.json"
    p.write_text(json.dumps(settings, indent=2))
    return p


def _git_common_dir(worktree) -> str | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--path-format=absolute",
                            "--git-common-dir"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def build_invocation(engine: str, *, role: str, worktree: Path, prompt: str, prompt_file: Path,
                     run_dir: Path, cfg: dict, frozen: list[str], attempt: int = 1,
                     read_only: bool = False, schema: dict | None = None,
                     milestone: str = "") -> Invocation:
    """role: build | review | intake. read_only is for intake. Prompt travels via stdin or
    argv depending on the engine's CLI."""
    run_dir = Path(run_dir)
    ecfg = cfg.get("engines", {}).get(engine, {})
    last = run_dir / f"engine-{role}-{attempt}.last.txt"
    # JSON list: read by harness.hooks_adapters (the in-engine guard). Must stay JSON, since an
    # unreadable frozen file makes the guard fail closed and block every tool call.
    frozen_file = run_dir / "frozen.json"
    frozen_file.write_text(json.dumps(list(frozen)))
    env = base_env({"HARNESS_ROOT": str(worktree), "HARNESS_FROZEN_FILE": str(frozen_file),
                    "HARNESS_ROLE": role, "HARNESS_ATTEMPT": str(attempt),
                    "HARNESS_LAST_MESSAGE": str(last), "HARNESS_RUN_DIR": str(run_dir),
                    "HARNESS_MILESTONE": milestone})
    schema_file = None
    if schema is not None:
        schema_file = run_dir / "schema.json"
        schema_file.write_text(json.dumps(schema))
    if engine == "codex":
        # Default "bypass" (inside the disposable worktree only): builders and reviewers must
        # reach the Docker daemon for real-stack tests and commit (a worktree's git metadata
        # lives outside the workspace-write roots). The external gate stays the authority.
        # Intake is always read-only; "workspace-write" remains a per-project option.
        sandbox = "read-only" if read_only else ecfg.get("sandbox", "bypass")
        argv = ["codex", "-c", 'approval_policy="never"', "exec"]
        if sandbox == "bypass":
            argv += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            argv += ["--sandbox", sandbox]
            if sandbox == "workspace-write":
                common = _git_common_dir(worktree)
                if common:
                    argv += ["--add-dir", common]  # lets codex commit inside the worktree
        argv += ["-C", str(worktree), "--json", "-o", str(last),
                 "-c", f'model_reasoning_effort="{ecfg.get("effort", "high")}"']
        if ecfg.get("model"):
            argv += ["--model", ecfg["model"]]
        if schema_file:
            argv += ["--output-schema", str(schema_file)]
        argv.append("-")
        return Invocation(argv, env, prompt, last)
    if engine == "claude":
        argv = ["claude", "-p", "--output-format", "json",
                "--strict-mcp-config", "--mcp-config", CLAUDE_EMPTY_MCP,
                "--model", ecfg.get("model", "opus"), "--effort", ecfg.get("effort", "high")]
        if read_only:
            argv += ["--permission-mode", "plan", "--allowedTools", "Read,Grep,Glob"]
        else:
            argv += ["--dangerously-skip-permissions", "--settings", str(claude_settings(run_dir))]
        if ecfg.get("max_usd_per_run"):
            argv += ["--max-budget-usd", str(ecfg["max_usd_per_run"])]
        if schema is not None:
            argv += ["--json-schema", json.dumps(schema)]
        return Invocation(argv, env, prompt, last)
    if engine == "hermes":
        if read_only:
            raise ValueError("hermes engine has no read-only mode")
        # --accept-hooks: the harness-coder profile's guard/verify hooks run without the
        # interactive first-use consent prompt (only in this dedicated profile).
        return Invocation(["hermes", "-p", ecfg.get("profile", "harness-coder"), "-z", prompt,
                           "--yolo", "--accept-hooks"], env, "", last)
    if engine == "agy":
        if read_only:
            raise ValueError("agy engine has no read-only mode")
        return Invocation(["agy", "-p", prompt, "--dangerously-skip-permissions"], env, "", last)
    if engine == "fake":
        script = os.environ.get("HARNESS_FAKE_ENGINE")
        if not script:
            raise ValueError("HARNESS_FAKE_ENGINE is not set")
        return Invocation([sys.executable, script, str(prompt_file)], env, "", last)
    raise ValueError(f"unknown engine {engine}")


def parse_output(engine: str, log: Path, last: Path | None) -> dict:
    """Best-effort info from engine output: final text, cost, is_error."""
    info: dict = {}
    text = Path(log).read_text(errors="replace") if Path(log).exists() else ""
    if engine == "claude":
        try:
            d = json.loads(text[text.find("{"):])
            info.update(cost_usd=d.get("total_cost_usd"), turns=d.get("num_turns"),
                        is_error=bool(d.get("is_error")),
                        final=str(d.get("result", ""))[-1500:])
            if d.get("structured_output") is not None:
                info["structured_output"] = d["structured_output"]
        except Exception:
            info["final"] = text[-1500:]
    else:
        info["final"] = (last.read_text(errors="replace")[-1500:]
                         if last and Path(last).exists() else text[-1500:])
    return info
