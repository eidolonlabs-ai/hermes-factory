"""harness CLI: init, setup, doctor, intake, freeze, run, wait, gate, pipeline, plan add, status, note."""
from __future__ import annotations

import argparse
import json
import shutil
import os
import subprocess
import sys
import time
from pathlib import Path

from . import engines, state, workspace
from .evidence import now, read_json, tail
from .resources import data_dir
from .models import (ConfigError, DEFAULT_CONFIG, load_config, load_plan, milestone_def,
                     validate_config, validate_milestone)


def out(obj) -> None:
    print(json.dumps(obj, default=str))


def fail(msg: str, code: int = 2) -> int:
    print(json.dumps({"error": msg}), file=sys.stdout)
    print(f"harness: {msg}", file=sys.stderr)
    return code


def resolve(args) -> tuple[Path, str]:
    repo = Path(args.repo or os.getcwd()).expanduser().resolve()
    project = args.project
    if not project:
        cfg = repo / ".harness" / "config.json"
        data = read_json(cfg)
        project = (data or {}).get("project") or state.find_project_by_repo(str(repo))
    if not project:
        raise ConfigError(f"cannot determine project for {repo}; pass --project or run `harness init`")
    if state.exists(project):
        repo = Path(state.load_state(project)["repo"])
    return repo, project


# ---------------------------------------------------------------- commands
TEMPLATE_DIR = data_dir("template")


def _copy_template(repo: Path, project: str, host: bool) -> list[str]:
    """Copy template/ files that do not exist yet. Never overwrites. Returns added paths."""
    added = []
    if not TEMPLATE_DIR.is_dir():
        return added
    for src in sorted(TEMPLATE_DIR.rglob("*")):
        rel = src.relative_to(TEMPLATE_DIR)
        if src.is_dir() or rel.as_posix() == ".harness/config.json":
            continue
        if host and rel.name in ("compose.yaml", "compose.preview.yaml"):
            continue
        dst = repo / rel
        if dst.exists() or dst.is_symlink():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
        else:
            shutil.copy2(src, dst)
        added.append(rel.as_posix())
    return added


def cmd_init(a) -> int:
    repo = Path(a.repo or os.getcwd()).expanduser().resolve()
    project = a.project or repo.name.replace(" ", "-")
    raw = {"project": project}
    if a.stack == "host":
        if not a.reason:
            return fail("--stack host requires --reason")
        raw["stack"] = {"type": "host", "reason": a.reason}
    cfg_path = repo / ".harness" / "config.json"
    validate_config(raw)
    copied = _copy_template(repo, project, a.stack == "host")
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        full = {k: v for k, v in DEFAULT_CONFIG.items()}
        full.update(raw)
        cfg_path.write_text(json.dumps(full, indent=2) + "\n")
    is_git = subprocess.run(["git", "-C", str(repo), "rev-parse"], capture_output=True).returncode == 0
    if is_git and a.commit:
        workspace.git(repo, "add", ".harness/config.json", *copied)
        if workspace.git(repo, "diff", "--cached", "--name-only"):
            workspace.git(repo, "commit", "-q", "-m", "chore(harness): init config")
    state.init_project(project, str(repo))
    out({"project": project, "repo": str(repo), "config": str(cfg_path), "home": str(state.home()),
         "git": is_git, "template_files_added": copied})
    return 0


def cmd_setup(a) -> int:
    from .hermes_setup import run_setup
    res = run_setup(dry_run=a.dry_run, with_profiles=a.profiles)
    out(res)
    return 0 if res.get("ok") else 1


def cmd_doctor(a) -> int:
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": ok, "detail": detail})
    add("python>=3.11", sys.version_info >= (3, 11), sys.version.split()[0])
    import shutil
    add("git", bool(shutil.which("git")), shutil.which("git") or "missing")
    add("harness-hook on PATH", bool(shutil.which("harness-hook")),
        shutil.which("harness-hook") or "missing: the Hermes guard plugin needs it (re-run install.sh)")
    add("template", TEMPLATE_DIR.is_dir(), str(TEMPLATE_DIR))
    try:
        h = state.home()
        add("home writable", os.access(h, os.W_OK), str(h))
    except OSError as e:
        add("home writable", False, str(e))
    try:
        from . import compose
        ok, why = compose.docker_available()
        add("docker", ok, why)
    except ImportError:
        add("docker", False, "compose module unavailable")
    for e in ("codex", "claude", "hermes", "agy"):
        ok, why = engines.probe(e)
        add(f"engine:{e}", ok, why)
    for m in ("guard", "hooks_adapters", "hygiene", "audit_diff", "detect", "compose"):
        try:
            __import__(f"harness.{m}")
            add(f"module:{m}", True)
        except ImportError as e:
            add(f"module:{m}", False, str(e))
    # Docker + compose are required (CONTRACT §4) unless every registered project opted out.
    required = {"python>=3.11", "git", "home writable", "docker"}
    ok = all(c["ok"] for c in checks if c["check"] in required)
    out({"ok": ok, "checks": checks})
    return 0 if ok else 1


def cmd_intake(a) -> int:
    from .intake import run_intake
    cfg = None
    try:
        repo, _ = resolve(a)
        cfg = load_config(repo)
    except (ConfigError, KeyError):
        pass
    res = run_intake(Path(a.source), a.engine, timeout_s=a.timeout, cfg=cfg)
    out({k: res.get(k) for k in ("run_id", "status", "report", "reason", "run_dir")})
    return 0 if res["status"] in ("needs_clarification", "ready_for_planning") else 1


def cmd_freeze(a) -> int:
    from . import holdout
    repo, project = resolve(a)
    try:
        out(holdout.freeze(repo, project, force=a.force))
    except ValueError as e:
        return fail(str(e))
    return 0


def _run_args(a) -> list[str]:
    argv = ["run", "--milestone", a.milestone, "--role", a.role, "--engine", a.engine]
    if a.attempts:
        argv += ["--attempts", str(a.attempts)]
    if a.feedback_file:
        argv += ["--feedback-file", a.feedback_file]
    if a.review_engine:
        argv += ["--review-engine", a.review_engine]
    if a.no_merge:
        argv += ["--no-merge"]
    return argv


def cmd_run(a) -> int:
    from . import runner
    repo, project = resolve(a)
    feedback = Path(a.feedback_file).read_text() if a.feedback_file else ""
    if a.detach:
        run_id = a.run_id or runner.new_run_id(a.role, a.milestone)
        rdir = state.run_dir(project, run_id)
        rdir.mkdir(parents=True, exist_ok=True)
        log = (rdir / "driver.log").open("w")
        env = engines.base_env()
        p = subprocess.Popen([sys.executable, "-m", "harness", *_run_args(a), "--project", project,
                              "--repo", str(repo), "--run-id", run_id],
                             stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, cwd=str(repo), env=env)
        runner.write_status(rdir, state="running", pid=p.pid, milestone=a.milestone, role=a.role,
                            engine=a.engine, started=now())
        out({"run_id": run_id, "detached": True, "pid": p.pid})
        return 0
    res = runner.execute_run(project, a.milestone, a.role, a.engine, attempts=a.attempts,
                             feedback=feedback, review_engine=a.review_engine,
                             merge=not a.no_merge, run_id=a.run_id)
    out(runner.run_summary(state.run_dir(project, res["run_id"])))
    return runner.EXIT.get(res["status"], 1)


def cmd_wait(a) -> int:
    from . import runner
    repo, project = resolve(a)
    rdir = state.run_dir(project, a.run_id)
    if not (rdir / "status.json").exists():
        return fail(f"unknown run {a.run_id}")
    deadline = time.time() + a.max
    while True:
        s = read_json(rdir / "status.json", {})
        if s.get("state") not in (None, "running"):
            summ = runner.run_summary(rdir)
            if s["state"] == "crashed":
                summ["driver_log_tail"] = tail(rdir / "driver.log", 30)
            out(summ)
            return runner.EXIT.get(s["state"], 1)
        pid = s.get("pid")
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                pass
        if not alive:
            out({"run_id": a.run_id, "state": "crashed", "driver_log_tail": tail(rdir / "driver.log", 30)})
            return 3
        if time.time() >= deadline:
            out({"run_id": a.run_id, "state": "running", "phase": s.get("phase"),
                 "attempt": s.get("attempt"), "started": s.get("started")})
            return 10
        time.sleep(min(2.0, max(0.05, deadline - time.time())))


def cmd_gate(a) -> int:
    from . import gate as gate_mod
    repo, project = resolve(a)
    st = state.load_state(project)
    cfg = load_config(repo)
    wt = Path(a.worktree).resolve() if a.worktree else repo
    ms = milestone_def(repo, a.milestone, st.get("extra_milestones"))
    base = a.base
    if not base:
        base = workspace.git(wt, "rev-parse", "HEAD")
        if wt != repo:
            base = workspace.git(wt, "merge-base", "HEAD", workspace.current_branch(repo))
    run_id = f"gate-{int(time.time())}"
    ctx = gate_mod.GateContext(project=project, repo=repo, worktree=wt, base=base, milestone=ms,
                               config=cfg, freeze_sha=st.get("freeze_sha"), frozen=st.get("frozen", []),
                               run_id=run_id, out_dir=state.run_dir(project, run_id))
    ok, checks = gate_mod.run_gate(ctx)
    out({"ok": ok, "milestone": a.milestone, "gate_json": str(ctx.out_dir / "gate.json"),
         "checks": [{"id": c.id, "status": c.status, "summary": c.summary} for c in checks]})
    return 0 if ok else 1


def cmd_pipeline(a) -> int:
    from .pipeline import run_pipeline
    repo, project = resolve(a)
    summary = run_pipeline(project, until=a.until, next_only=a.next, engine=a.engine)
    out(summary)
    return 0 if summary["status"] in ("completed", "checkpoint", "stopped") else 1


def cmd_plan_add(a) -> int:
    repo, project = resolve(a)
    st = state.load_state(project)
    ids = {m["id"] for m in load_plan(repo)["milestones"]} | set(st.get("extra_milestones", {}))
    m = {"id": a.milestone, "title": a.title or a.goal[:60], "goal": a.goal,
         "acceptance": a.acceptance or [f"scripts/verify.sh {a.verify_as or a.milestone} passes"],
         "allowed_paths": a.allowed_path or ["**"]}
    if a.verify_as:
        m["verify_as"] = a.verify_as
    if a.checkpoint:
        m["checkpoint"] = True
    try:
        validate_milestone(m)
        if a.milestone in ids:
            raise ConfigError(f"milestone {a.milestone} already exists")
    except ConfigError as e:
        return fail(str(e))

    def f(s):
        s["extra_milestones"][a.milestone] = m
    state.update_state(project, f)
    out({"added": m})
    return 0


def cmd_status(a) -> int:
    repo, project = resolve(a)
    st = state.load_state(project)
    active = []
    d = state.runs_dir(project)
    if d.is_dir():
        for r in sorted(d.glob("*/status.json")):
            s = read_json(r, {})
            if s.get("state") == "running":
                pid = s.get("pid")
                try:
                    if pid:
                        os.kill(int(pid), 0)
                except (OSError, ValueError):
                    s["state"] = "dead"  # driver process gone (killed/crashed); not active
                    active_dead = True
                    continue
                active.append({"run_id": r.parent.name, **{k: s.get(k) for k in ("milestone", "role", "phase", "pid")}})
    try:
        plan_ids = [m["id"] for m in load_plan(repo)["milestones"]]
    except ConfigError:
        plan_ids = []
    out({"project": project, "repo": st["repo"], "freeze_sha": st.get("freeze_sha"),
         "plan": plan_ids, "extra_milestones": list(st.get("extra_milestones", {})),
         "done": sorted(st.get("done", {})), "interventions": len(st.get("interventions", [])),
         "cost_usd": st.get("cost_usd", 0), "active_runs": active, "recent_runs": st["runs"][-5:]})
    return 0


def cmd_note(a) -> int:
    repo, project = resolve(a)
    n = state.add_note(project, a.text)
    out({"intervention": n})
    return 0


def cmd_preview(a) -> int:
    repo, project = resolve(a)
    cfg = load_config(repo)
    if cfg["stack"]["type"] != "compose":
        return fail("preview needs stack.type compose")
    from . import compose
    log = state.runs_dir(project) / "preview.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    res = compose.preview(str(repo), cfg["stack"].get("file", "compose.yaml"), project,
                          down=a.down, log=log)
    out(res)
    return 0 if res.get("ok", res.get("down")) else 1


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="project repo (default: cwd)")
    common.add_argument("--project", help="project name (default: from .harness/config.json)")
    ap = argparse.ArgumentParser(prog="harness")
    from . import __version__
    ap.add_argument("--version", action="version", version=f"harness {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        p = sub.add_parser(name, parents=[common], **kw)
        p.set_defaults(func=fn)
        return p
    p = add("init", cmd_init)
    p.add_argument("--stack", choices=["compose", "host"], default="compose")
    p.add_argument("--reason")
    p.add_argument("--no-commit", dest="commit", action="store_false")
    p = add("setup", cmd_setup, help="install the Hermes skills, profiles and guard plugin")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-profiles", dest="profiles", action="store_false",
                   help="skills only; do not create or change Hermes profiles")
    add("doctor", cmd_doctor)
    p = add("intake", cmd_intake)
    p.add_argument("source")
    p.add_argument("--engine", required=True, choices=engines.ENGINE_NAMES if hasattr(engines, "ENGINE_NAMES") else None)
    p.add_argument("--timeout", type=int, default=1200)
    p = add("freeze", cmd_freeze)
    p.add_argument("--force", action="store_true")
    p = add("run", cmd_run)
    p.add_argument("--milestone", required=True)
    p.add_argument("--role", choices=["build", "review"], required=True)
    p.add_argument("--engine", required=True)
    p.add_argument("--attempts", type=int)
    p.add_argument("--feedback-file")
    p.add_argument("--review-engine", help="chain a review phase after a passing build (or 'cross')")
    p.add_argument("--no-merge", action="store_true")
    p.add_argument("--detach", action="store_true")
    p.add_argument("--run-id")
    p = add("wait", cmd_wait)
    p.add_argument("run_id")
    p.add_argument("--max", type=float, default=540)
    p = add("gate", cmd_gate)
    p.add_argument("--milestone", required=True)
    p.add_argument("--worktree")
    p.add_argument("--base")
    p = add("pipeline", cmd_pipeline)
    p.add_argument("--until")
    p.add_argument("--next", action="store_true")
    p.add_argument("--engine", help="override builder engine for all milestones")
    p = add("plan", cmd_plan_add)
    p.add_argument("action", choices=["add"])
    p.add_argument("milestone")
    p.add_argument("--goal", required=True)
    p.add_argument("--title")
    p.add_argument("--verify-as")
    p.add_argument("--acceptance", action="append")
    p.add_argument("--allowed-path", action="append")
    p.add_argument("--checkpoint", action="store_true")
    p = add("preview", cmd_preview, help="boot the merged app with published ports (own project)")
    p.add_argument("--down", action="store_true", help="tear the preview down")
    add("status", cmd_status)
    p = add("note", cmd_note)
    p.add_argument("text")
    return ap


def _sigterm_to_interrupt() -> None:
    """kill <pid> ends a run like Ctrl-C: status "interrupted", lock released, stacks torn down."""
    import signal

    def handler(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, handler)
    except ValueError:  # not in the main thread
        pass


def main(argv: list[str] | None = None) -> int:
    _sigterm_to_interrupt()
    from .models import ENGINE_NAMES  # noqa: F401
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, KeyError, ValueError, workspace.WorkspaceError) as e:
        return fail(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
