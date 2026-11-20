"""Engine argv builders and probes (DESIGN §5). Argv lists only, never a shell."""
from __future__ import annotations

import json
import shlex
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .models import ConfigError, ENGINE_NAMES
from .usage import supports_hermes_usage, token_counts

CLAUDE_EMPTY_MCP = '{"mcpServers":{}}'
PKG_PARENT = str(Path(__file__).resolve().parent.parent)


@dataclass
class Invocation:
    argv: list
    env: dict
    stdin_text: str = ""
    last_message: Path | None = None
    extra: dict = field(default_factory=dict)
    usage_file: Path | None = None


def other_vendor(engine: str) -> str:
    return {"codex": "claude", "claude": "codex", "hermes": "claude", "agy": "claude",
            "fake": "fake"}[engine]


def resolve_review_engine(cfg_value: str, builder: str, cross: dict | None = None) -> str:
    if cfg_value != "cross":
        return cfg_value
    if cross is None:
        return other_vendor(builder)
    if builder not in cross:
        raise ConfigError(f"cross has no reviewer configured for {builder!r}")
    return cross[builder]


def probe(engine: str) -> tuple[bool, str]:
    if engine not in ENGINE_NAMES:
        return False, f"unknown engine {engine}"
    if engine == "fake":
        p = os.environ.get("FACTORY_FAKE_ENGINE")
        if p and Path(p).is_file():
            return True, p
        return False, "FACTORY_FAKE_ENGINE is not set to an existing script"
    exe = {"codex": "codex", "claude": "claude", "hermes": "hermes", "agy": "agy"}[engine]
    path = shutil.which(exe)
    return (True, path) if path else (False, f"{exe} not found on PATH")


def base_env(extra: dict | None = None, *, include_pkg_pythonpath: bool = False) -> dict:
    env = dict(os.environ)
    env["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
    for k in list(env):  # do not inherit a Hermes worker's board identity
        if k.startswith("HERMES_KANBAN"):
            env.pop(k)
    added = env.pop("_FACTORY_PKG_PYTHONPATH", None)
    cur_pp = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    if include_pkg_pythonpath:
        if PKG_PARENT not in cur_pp:
            cur_pp.append(PKG_PARENT)
        env["PYTHONPATH"] = os.pathsep.join(cur_pp)
        env["_FACTORY_PKG_PYTHONPATH"] = PKG_PARENT
    elif added:
        cur_pp = [p for p in cur_pp if p != added]
        if cur_pp:
            env["PYTHONPATH"] = os.pathsep.join(cur_pp)
        else:
            env.pop("PYTHONPATH", None)
    env.update(extra or {})
    return env


def claude_settings(run_dir: Path) -> Path:
    """Per-run settings JSON: PreToolUse guard hook. Lives outside the repo."""
    settings = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": f"{shlex.quote(sys.executable)} -m factory.hooks_adapters claude"}]}]}}
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
    # JSON list: read by factory.hooks_adapters (the in-engine guard). Must stay JSON, since an
    # unreadable frozen file makes the guard fail closed and block every tool call.
    frozen_file = run_dir / "frozen.json"
    frozen_file.write_text(json.dumps(list(frozen)))
    env = base_env({"FACTORY_ROOT": str(worktree), "FACTORY_FROZEN_FILE": str(frozen_file),
                    "FACTORY_ROLE": role, "FACTORY_ATTEMPT": str(attempt),
                    "FACTORY_LAST_MESSAGE": str(last), "FACTORY_RUN_DIR": str(run_dir),
                    "FACTORY_MILESTONE": milestone},
                   include_pkg_pythonpath=(engine in ("claude", "fake")))
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
            argv += ["--permission-mode", "plan", "--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob"]
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
        # --accept-hooks: the factory-coder profile's guard/verify hooks run without the
        # interactive first-use consent prompt (only in this dedicated profile).
        argv = ["hermes", "-p", ecfg.get("profile", "factory-coder"), "-z", prompt,
                "--yolo", "--accept-hooks"]
        executable = shutil.which("hermes")
        report = None
        if executable and supports_hermes_usage(executable):
            report = run_dir / f"engine-{role}-{attempt}.usage.json"
            report.unlink(missing_ok=True)
            argv += ["--usage-file", str(report)]
        return Invocation(argv, env, "", last, usage_file=report)
    if engine == "agy":
        if read_only:
            raise ValueError("agy engine has no read-only mode")
        return Invocation(["agy", "-p", prompt, "--dangerously-skip-permissions"], env, "", last)
    if engine == "fake":
        script = os.environ.get("FACTORY_FAKE_ENGINE")
        if not script:
            raise ValueError("FACTORY_FAKE_ENGINE is not set")
        return Invocation([sys.executable, script, str(prompt_file)], env, "", last)
    raise ValueError(f"unknown engine {engine}")


def _extract_claude_json(text: str) -> dict | None:
    """Extract Claude's JSON result envelope even when stderr lines precede/follow stdout."""
    dec = json.JSONDecoder()
    fallback = None
    idx = 0
    while True:
        pos = text.find("{", idx)
        if pos < 0:
            return fallback
        try:
            obj, end = dec.raw_decode(text, pos)
            if isinstance(obj, dict):
                if obj.get("type") == "result" or any(k in obj for k in ("result", "structured_output", "total_cost_usd")):
                    return obj
                fallback = obj
            idx = end
        except json.JSONDecodeError:
            idx = pos + 1


def parse_output(engine: str, log: Path, last: Path | None) -> dict:
    """Best-effort info from engine output: final text, cost, is_error."""
    info: dict = {}
    text = Path(log).read_text(errors="replace") if Path(log).exists() else ""
    if engine == "claude":
        d = _extract_claude_json(text)
        if d is not None:
            info.update(cost_usd=d.get("total_cost_usd"), turns=d.get("num_turns"),
                        is_error=bool(d.get("is_error")),
                        final=str(d.get("result", ""))[-1500:])
            stats = d.get("usage")
            if isinstance(stats, dict):
                info["tokens"] = token_counts({"input": stats.get("input_tokens"),
                    "output": stats.get("output_tokens"), "cache_read": stats.get("cache_read_input_tokens"),
                    "cache_write": stats.get("cache_creation_input_tokens")})
            if d.get("structured_output") is not None:
                info["structured_output"] = d["structured_output"]
        else:
            info["final"] = text[-1500:]
    else:
        info["final"] = (last.read_text(errors="replace")[-1500:]
                         if last and Path(last).exists() else text[-1500:])
    return info
