"""Pipeline: iterate plan milestones not yet done: build -> gate -> review -> gate -> merge.
Stops at checkpoints, red gates, budget, non-ff merge policy, or unavailable engines."""
from __future__ import annotations

from pathlib import Path

from . import engines, state
from .evidence import now
from .models import load_config, load_plan, validate_milestone


def pick_builder(ms: dict, cfg: dict) -> str:
    if ms.get("builder"):
        return ms["builder"]
    return cfg["roles"]["ui" if ms.get("ui") else "backend"]


def pick_reviewer(ms: dict, cfg: dict, builder: str) -> str:
    return engines.resolve_review_engine(ms.get("reviewer") or cfg["roles"]["review"], builder)


def all_milestones(repo: Path, st: dict) -> list[dict]:
    ms = list(load_plan(repo)["milestones"])
    ids = {m["id"] for m in ms}
    for mid, m in (st.get("extra_milestones") or {}).items():
        if mid not in ids:
            ms.append(validate_milestone(dict(m), f"extra {mid}"))
    return ms


def pending_milestones(repo: Path, st: dict) -> list[dict]:
    return [m for m in all_milestones(repo, st) if m["id"] not in st.get("done", {})]


def run_pipeline(project: str, *, until: str | None = None, next_only: bool = False,
                 engine: str | None = None, runner=None) -> dict:
    from . import runner as runner_mod
    run = runner or runner_mod.execute_run
    st = state.load_state(project)
    repo = Path(st["repo"])
    cfg = load_config(repo)
    summary = {"project": project, "started": now(), "milestones": [], "status": "completed",
               "stopped_at": None, "reason": ""}

    def stop(status, mid, reason):
        summary.update(status=status, stopped_at=mid, reason=reason, finished=now())
        return summary

    if not st.get("freeze_sha"):
        return stop("not_frozen", None, "run `factory freeze` after M0 is approved")
    ms_list = all_milestones(repo, st)
    if until:
        ids = [m["id"] for m in ms_list]
        if until not in ids:
            return stop("error", until, f"unknown milestone {until}")
        ms_list = ms_list[:ids.index(until) + 1]
    done = st.get("done") or {}
    todo = [m for m in ms_list if m["id"] not in done]
    if not todo:
        if until:
            return stop("stopped", until, f"milestone {until} already reached")
        summary["finished"] = now()
        return summary
    for ms in todo:
        mid = ms["id"]
        builder = engine or pick_builder(ms, cfg)
        reviewer = pick_reviewer(ms, cfg, builder)
        for e in (builder, reviewer):
            ok, why = engines.probe(e)
            if not ok:
                return stop("engine_unavailable", mid, why)
        res = run(project, mid, "build", builder, review_engine=reviewer)
        summary["milestones"].append({k: res.get(k) for k in (
            "run_id", "milestone", "status", "passed", "merged", "summary", "worktree", "branch")}
            | {"builder": builder, "reviewer": reviewer})
        if not res["passed"]:
            return stop({"needs_human": "needs_human", "budget": "budget"}.get(res["status"], "red"),
                        mid, res.get("summary", ""))
        if not res.get("merged"):
            return stop("awaiting_merge", mid, res.get("summary", "merge policy is not ff"))
        if ms.get("checkpoint"):
            return stop("checkpoint", mid, f"{mid} is flagged as a checkpoint; human approval needed")
        if until == mid or next_only:
            return stop("stopped", mid, "reached --until/--next limit")
    if until:
        return stop("stopped", until, "reached --until limit")
    summary["finished"] = now()
    return summary
