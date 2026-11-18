"""One run: lock -> worktree -> engine attempts with scrubbed feedback -> gate -> result.json.

A `build` run may chain a cross-vendor `review` phase in the same worktree (then gates again);
then the merge policy applies (ff | pr | human). Worktrees are kept on failure.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import engines, gate, state, workspace
from .engines import resolve_review_engine
from .evidence import now, read_json, tail, write_json, write_result
from .models import ConfigError, load_config, milestone_def, validate_run_id
from .process import run_process

PROMPTS = Path(__file__).parent / "prompts"
PASSED, FAILED, NEEDS_HUMAN = "passed", "failed", "needs_human"
EXIT = {"passed": 0, "crashed": 3}


def new_run_id(role: str, milestone: str) -> str:
    return f"{dt.datetime.now():%Y%m%d-%H%M%S}-{role}-{milestone}-{uuid.uuid4().hex[:4]}"


def render(template: str, **kw) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(kw.get(m.group(1), m.group(0))), template)


@contextmanager
def _status_lock(rdir: Path):
    rdir.mkdir(parents=True, exist_ok=True)
    with open(rdir / "status.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def write_status(rdir: Path, **kw) -> None:
    p = rdir / "status.json"
    with _status_lock(rdir):
        s = read_json(p, {})
        s.update(kw)
        write_json(p, s)


def set_detached_pid(rdir: Path, pid: int) -> None:
    """Record child pid only if the detached child has not already finished."""
    p = rdir / "status.json"
    with _status_lock(rdir):
        s = read_json(p, {})
        if s.get("state") in (None, "running") and not s.get("pid"):
            s["pid"] = pid
            write_json(p, s)


def _expand_frozen(repo, freeze_sha, frozen: list[str]) -> list[str]:
    if not freeze_sha:
        return list(frozen)
    out: list[str] = []
    for f in frozen:
        if f.endswith("/"):
            try:
                names = workspace.git(repo, "ls-tree", "-r", "--name-only", "-z", freeze_sha, "--", f)
            except Exception:
                out.append(f)
                continue
            out += [n for n in names.split("\0") if n]
        else:
            out.append(f)
    return out


def _register_active(c, engine: str, env: dict):
    """Hermes shell hooks run with a scrubbed env and the profile home as cwd, so the guard
    hook finds live runs through <FACTORY_HOME>/active/<run_id>.json (see hooks_adapters)."""
    if engine != "hermes":
        return None
    d = state.home() / "active"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{c.run_id}.json"
    f.write_text(json.dumps({"pid": os.getpid(), "run_id": c.run_id, "root": str(c.ws.path),
                             "frozen_file": env["FACTORY_FROZEN_FILE"],
                             "milestone": env.get("FACTORY_MILESTONE", "")}))
    return f


def _down_engine_stack(c) -> None:
    """Tear down the compose project the engine used for its own test runs (if any)."""
    if c.cfg["stack"]["type"] != "compose":
        return
    try:
        from . import compose
        compose.down_project(c.compose_proj, str(c.ws.path), c.rdir / "engine-stack-down.log")
    except Exception:  # best effort; the gate uses its own, separate project
        pass


def compose_project(project: str, run_id: str) -> str:
    try:
        from . import compose
        return compose.project_name(project, run_id)
    except Exception:
        return re.sub(r"[^a-z0-9_-]", "-", f"{project}-{run_id}".lower())[:60]


def build_prompt(role: str, ms: dict, *, project, repo, frozen, base_sha, engine, feedback,
                 compose_proj) -> str:
    mid = ms["id"]
    name = {("build", True): "architect", ("review", True): "architect_review",
            ("build", False): "build", ("review", False): "review"}[(role, mid == "M0")]
    tpl = (PROMPTS / f"{name}.md").read_text()
    acc = "\n".join(f"- {a}" for a in ms.get("acceptance", [])) or "- (see goal)"
    fb = ""
    if feedback:
        fb = ("\n## PREVIOUS ATTEMPT FAILED THE EXTERNAL GATE / FEEDBACK (must address)\n```\n"
              + feedback.strip() + "\n```\nFind and fix the root cause in implementation code. "
              "Do not weaken, skip or delete tests.\n")
    return render(tpl, project=project, repo=str(repo), milestone=mid, mid_lower=mid.lower(),
                  title=ms.get("title", ""), goal=ms.get("goal", ""), acceptance=acc,
                  allowed_paths=", ".join(ms.get("allowed_paths", [])) or "(any)",
                  frozen=", ".join(frozen) or "(none yet)", verify_id=ms.get("verify_as", mid),
                  compose_project=compose_proj, base_sha=base_sha, engine=engine,
                  other_engine=engines.other_vendor(engine), feedback=fb)


class _Ctx:
    pass


def _phase(c: _Ctx, role: str, engine: str, max_attempts: int, feedback: str) -> dict:
    """Engine attempts + gate for one role. Returns dict(status, passed, checks, history)."""
    history, checks = [], []
    for n in range(1, max_attempts + 1):
        if time.monotonic() > c.deadline:
            return dict(status="budget", passed=False, checks=checks, history=history,
                        summary="run_timeout_min exceeded")
        if c.cost >= c.cfg["budgets"]["project_max_usd"]:
            return dict(status="budget", passed=False, checks=checks, history=history,
                        summary="project_max_usd exceeded")
        write_status(c.rdir, role=role, phase="engine", attempt=n, engine=engine)
        pf = c.rdir / f"prompt-{role}-{n}.md"
        pf.write_text(build_prompt(role, c.ms, project=c.project, repo=c.ws.path, frozen=c.frozen,
                                   base_sha=c.base_sha, engine=engine, feedback=feedback,
                                   compose_proj=c.compose_proj))
        inv = engines.build_invocation(engine, role=role, worktree=c.ws.path, prompt=pf.read_text(),
                                       prompt_file=pf, run_dir=c.rdir, cfg=c.cfg, frozen=c.guard_frozen,
                                       attempt=n, milestone=c.ms.get("verify_as") or c.ms["id"])
        inv.env["COMPOSE_PROJECT_NAME"] = c.compose_proj
        remaining = max(1.0, c.deadline - time.monotonic())
        active = _register_active(c, engine, inv.env)
        try:
            res = run_process(inv.argv, c.ws.path,
                              min(c.cfg["budgets"]["engine_timeout_min"] * 60, remaining),
                              c.rdir / f"engine-{role}-{n}.log", inv.stdin_text, inv.env)
        finally:
            if active:
                active.unlink(missing_ok=True)
        _down_engine_stack(c)  # agents boot stacks while working; never leave them running
        info = engines.parse_output(engine, Path(res.log), inv.last_message)
        info.update(rc=res.returncode, timed_out=res.timed_out, seconds=int(res.duration_s))
        c.cost += float(info.get("cost_usd") or 0)
        c.run_cost += float(info.get("cost_usd") or 0)
        entry = {"role": role, "attempt": n, "engine": engine, "prompt": pf.name,
                 "engine_log": Path(res.log).name,
                 "engine_info": {k: v for k, v in info.items() if k != "structured_output"}}
        history.append(entry)
        if res.launch_error:
            return dict(status="engine_unavailable", passed=False, checks=checks, history=history,
                        summary=f"{engine} could not start: {res.launch_error}")
        workspace.commit_leftovers(c.ws.path, f"chore({c.ms['id'].lower()}): factory {role} attempt {n} ({engine})")
        write_status(c.rdir, phase="gate")
        gctx = gate.GateContext(project=c.project, repo=c.repo, worktree=c.ws.path, base=c.ws.base,
                                milestone=c.ms, config=c.cfg, freeze_sha=c.freeze_sha,
                                frozen=c.frozen, run_id=c.run_id,
                                out_dir=c.rdir / f"gate-{role}-{n}", env={})
        ok, checks = gate.run_gate(gctx)
        entry["gate"] = {"ok": ok, "dir": gctx.out_dir.name,
                         "checks": [{"id": k.id, "status": k.status, "summary": k.summary} for k in checks]}
        entry["sha"] = workspace.head_sha(c.ws.path)
        if ok:
            return dict(status="passed", passed=True, checks=checks, history=history, summary="gate passed")
        if gate.needs_human(checks):
            return dict(status="needs_human", passed=False, checks=checks, history=history,
                        summary="protected path changed; human decision needed")
        feedback = gate.feedback_from_checks(checks)
    bad = next((k for k in checks if k.status == "FAIL"), None)
    return dict(status="failed", passed=False, checks=checks, history=history,
                summary=(f"gate failed after {max_attempts} attempt(s): [{bad.id}] {bad.summary}"
                         if bad else "gate failed"))


def execute_run(project: str, milestone: str, role: str, engine: str, *, attempts: int | None = None,
                feedback: str = "", review_engine: str | None = None, merge: bool = True,
                run_id: str | None = None) -> dict:
    """Run one milestone role end to end. Always writes result.json; returns it."""
    run_id = validate_run_id(run_id) if run_id is not None else new_run_id(role, milestone)
    rdir = state.run_dir(project, run_id)
    rdir.mkdir(parents=True, exist_ok=True)
    result: dict = {"schema_version": 1, "run_id": run_id, "project": project, "milestone": milestone,
                    "role": role, "engine": engine, "status": "running", "passed": False,
                    "merged": False, "checks": [], "started": now()}
    write_status(rdir, state="running", pid=os.getpid(), milestone=milestone, role=role,
                 engine=engine, started=result["started"])
    lock = ws = None
    c = _Ctx()
    try:
        if role not in ("build", "review"):
            raise ConfigError(f"unknown role {role}")
        st = state.load_state(project)
        c.repo = Path(st["repo"])
        c.cfg = load_config(c.repo)
        c.project, c.run_id, c.rdir = project, run_id, rdir
        c.ms = milestone_def(c.repo, milestone, st.get("extra_milestones"))
        c.freeze_sha, c.frozen = st.get("freeze_sha"), list(st.get("frozen") or [])
        # The in-engine guard gets the frozen FILES as of the freeze commit: a frozen directory
        # ("tests/") freezes what existed then, while files added later (new regression tests,
        # including ones this run adds) stay editable. The gate checks dirs with --diff-filter=MDT.
        c.guard_frozen = _expand_frozen(c.repo, c.freeze_sha, c.frozen)
        if milestone != "M0" and not c.freeze_sha:
            raise ConfigError("project is not frozen; finish M0 and run `factory freeze` first")
        ok, why = engines.probe(engine)
        if not ok:
            result.update(status="engine_unavailable", summary=why)
            return result
        c.cost, c.run_cost = float(st.get("cost_usd", 0)), 0.0
        c.deadline = time.monotonic() + c.cfg["budgets"]["run_timeout_min"] * 60
        try:
            lock = workspace.acquire_lock(project, milestone, run_id)
        except workspace.WorkspaceError as e:
            result.update(status="locked", summary=str(e))
            return result
        ws = c.ws = workspace.create_worktree(c.repo, project, milestone, run_id)
        c.compose_proj = compose_project(project, run_id)
        c.base_sha = (st.get("done", {}).get(milestone, {}).get("base_sha") if role == "review" else None) or ws.base
        result.update(worktree=str(ws.path), branch=ws.branch, base_sha=ws.base)
        write_status(rdir, worktree=str(ws.path), branch=ws.branch)
        max_attempts = int(attempts or c.cfg["budgets"]["attempts"])
        phases = []
        r = _phase(c, role, engine, max_attempts, feedback)
        phases.append(r)
        if r["passed"] and role == "build" and review_engine:
            reng = resolve_review_engine(review_engine, engine)
            ok, why = engines.probe(reng)
            if not ok:
                r = dict(status="engine_unavailable", passed=False, checks=r["checks"], history=[],
                         summary=f"review engine unavailable: {why}")
            else:
                result["review_engine"] = reng
                r = _phase(c, "review", reng, int(c.cfg["budgets"]["review_rounds"]), "")
            phases.append(r)
        history = [h for p in phases for h in p["history"]]
        last = phases[-1]
        result.update(status=last["status"], passed=last["passed"], summary=last["summary"],
                      attempts=len(history), history=history,
                      checks=[k.to_dict() for k in last["checks"]],
                      head_sha=workspace.head_sha(ws.path))
        if last["checks"]:
            cand = next((k for k in last["checks"] if k.id == "candidate" and k.status == "PASS"), None)
            if cand:
                result["candidate_sha256"] = cand.details[0]
        if last["passed"]:
            policy = c.cfg["merge"] if merge else "none"
            result["merge_policy"] = policy
            if policy == "ff":
                ok, msg = workspace.merge_ff(ws)
                if ok:
                    result.update(merged=True, merge_sha=msg)
                    _record_done(project, milestone, run_id, msg, ws.base)
                    workspace.remove_worktree(ws, delete_branch=True)
                else:
                    result.update(status="failed", passed=False,
                                  summary=f"merge failed: {msg}; worktree kept")
            elif policy in ("pr", "human"):
                result["summary"] += f"; branch {ws.branch} awaits {'PR' if policy == 'pr' else 'human merge'}"
                workspace.remove_worktree(ws)  # branch keeps the commits
    except KeyboardInterrupt:
        result.update(status="interrupted", passed=False, summary="interrupted")
    except (ConfigError, KeyError, ValueError, workspace.WorkspaceError) as e:
        result.update(status="failed", passed=False, summary=f"{type(e).__name__}: {e}")
    except Exception as e:  # driver crash: recorded, never a pass
        import traceback
        result.update(status="crashed", passed=False, summary=f"{type(e).__name__}: {e}",
                      traceback=traceback.format_exc()[-1500:])
    finally:
        if ws is not None and getattr(c, "compose_proj", None):
            _down_engine_stack(c)  # also on interrupt: never leave an engine's stack running
        if lock:
            lock.release()
        result["finished"] = now()
        if ws:
            result["worktree_kept"] = ws.path.exists()
        result["cost_usd"] = getattr(c, "run_cost", 0.0)
        write_result(rdir, result)
        write_status(rdir, state=result["status"], phase="done", finished=result["finished"])
        try:
            _record_run(project, result)
        except Exception:
            pass
    return result


def _record_done(project, milestone, run_id, sha, base):
    def f(s):
        s["done"][milestone] = {"run_id": run_id, "sha": sha, "base_sha": base, "at": now()}
    state.update_state(project, f)


def _record_run(project, result):
    def f(s):
        s["runs"].append({k: result.get(k) for k in ("run_id", "milestone", "role", "engine",
                                                     "status", "passed", "merged")} | {"at": now()})
        s["cost_usd"] = float(s.get("cost_usd", 0)) + float(result.get("cost_usd") or 0)
    state.update_state(project, f)


def run_summary(rdir: Path) -> dict:
    """Short view of a finished run for `wait`."""
    r = read_json(rdir / "result.json", {})
    short = {k: r.get(k) for k in ("run_id", "milestone", "role", "engine", "status", "passed",
                                   "merged", "summary", "attempts", "base_sha", "head_sha",
                                   "worktree", "branch", "cost_usd")}
    if not r.get("passed"):
        bad = [c for c in r.get("checks", []) if c["status"] == "FAIL"]
        short["failed_checks"] = [{"id": c["id"], "summary": c["summary"],
                                  "details": c["details"][:10]} for c in bad]
        # last verify log tail for the operator (holdout raw logs are never shown)
        h = (r.get("history") or [{}])[-1]
        d = h.get("gate", {}).get("dir")
        if d and (rdir / d / "verify.log").exists():
            short["verify_tail"] = tail(rdir / d / "verify.log", 30)
    return short
