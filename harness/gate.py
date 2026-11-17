"""The gate (CONTRACT §2). Deterministic, exit-code based, first failure stops.

Order: scope, frozen, hygiene, compose-policy, verify, holdout, audit-diff, candidate.
NOT_RUN is never PASS; with require_tests a gate where no test check ran is a failure.
Sibling modules (hygiene, audit_diff, compose) are imported lazily; ImportError = NOT_RUN.
"""
from __future__ import annotations

import fnmatch
import os
import shlex
import subprocess
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import holdout, state, workspace
from .evidence import now, tail, write_json
from .process import run_process
from .types import Check

HUMAN_PREFIX = "HUMAN:"
IMPLICIT_ALLOWED = ["RFI.md", "docs/reviews/"]
STEPS = ["scope", "frozen", "hygiene", "compose-policy", "verify", "holdout", "audit-diff"]
TEST_CHECKS = ("verify", "m0-structure")


@dataclass
class GateContext:
    project: str
    repo: Path
    worktree: Path
    base: str
    milestone: dict
    config: dict
    freeze_sha: str | None
    frozen: list
    run_id: str
    out_dir: Path
    env: dict | None = None
    _compose: dict = field(default_factory=dict)

    @property
    def verify_id(self) -> str:
        return self.milestone.get("verify_as") or self.milestone["id"]

    @property
    def host(self) -> bool:
        return self.config["stack"]["type"] == "host"


def path_matches(path: str, pattern: str) -> bool:
    pat = pattern.strip()
    if pat in ("**", "*", "."):
        return True
    if pat.endswith("/"):
        return path.startswith(pat)
    return path == pat or fnmatch.fnmatch(path, pat) or path.startswith(pat + "/")


def needs_human(checks: list[Check]) -> bool:
    return any(c.id == "scope" and c.status == "FAIL" and c.summary.startswith(HUMAN_PREFIX)
               for c in checks)


# ------------------------------------------------------------------ steps
def _scope(ctx: GateContext) -> list[Check]:
    t0 = time.monotonic()
    status = workspace.changed_status(ctx.worktree, ctx.base)
    status = {p: s for p, s in status.items()}
    allowed = list(ctx.milestone.get("allowed_paths", [])) + IMPLICIT_ALLOWED
    protected_hits = []
    if ctx.freeze_sha:  # protected paths are enforced once the contract is frozen
        for p, s in sorted(status.items()):
            if s != "A" and any(path_matches(p, q) for q in ctx.config["protected"]):
                protected_hits.append(f"{s} {p}")
    if protected_hits:
        return [Check("scope", "FAIL", f"{HUMAN_PREFIX} protected path changed; human decision needed",
                      protected_hits[:30], duration_s=time.monotonic() - t0)]
    out = [p for p in sorted(status) if not any(path_matches(p, a) for a in allowed)]
    if out:
        return [Check("scope", "FAIL",
                      f"{len(out)} changed path(s) outside allowed_paths {ctx.milestone.get('allowed_paths')}",
                      out[:30], duration_s=time.monotonic() - t0)]
    return [Check("scope", "PASS", f"{len(status)} changed path(s) within scope",
                  duration_s=time.monotonic() - t0)]


def _frozen(ctx: GateContext) -> list[Check]:
    t0 = time.monotonic()
    if not ctx.freeze_sha or not ctx.frozen:
        return [Check("frozen", "NOT_RUN", "project not frozen yet")]
    # Added files are allowed (CONTRACT §6: builders may add tests); modified, deleted,
    # renamed or type-changed frozen files are not. Frozen entries may be directories.
    changed = workspace.git(ctx.worktree, "diff", "--name-only", "-z", "--no-renames",
                            "--diff-filter=MDT", ctx.freeze_sha, "--", *ctx.frozen).split("\0")
    missing = [p for p in ctx.frozen if not (ctx.worktree / p).exists()]
    bad = sorted(set(filter(None, changed)) | set(missing))
    if bad:
        return [Check("frozen", "FAIL", "frozen files modified or deleted since freeze",
                      bad[:30], duration_s=time.monotonic() - t0)]
    return [Check("frozen", "PASS",
                  f"frozen set intact ({len(ctx.frozen)} paths @ {ctx.freeze_sha[:10]})",
                  duration_s=time.monotonic() - t0)]


def _hygiene(ctx: GateContext) -> list[Check]:
    try:
        from . import hygiene
    except ImportError as e:
        return [Check("hygiene", "NOT_RUN", f"hygiene module unavailable: {e}")]
    return [hygiene.check_hygiene(ctx.worktree)]


def _base_env(ctx: GateContext) -> dict:
    """Environment for verify/holdout scripts (CONTRACT §5): artifacts dir, run id, milestone."""
    art = ctx.out_dir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    return {**os.environ, **(ctx.env or {}), "HARNESS_ARTIFACTS": str(art),
            "HARNESS_RUN_ID": ctx.run_id, "HARNESS_MILESTONE": ctx.verify_id,
            "HARNESS_PROJECT": ctx.project}


def _other_projects(project: str) -> list[str]:
    return [p for p in state.all_projects() if p != project]


def _policy(ctx: GateContext) -> list[Check]:
    if ctx.host:
        return [Check("compose-policy", "NOT_RUN", "stack.type is host: not isolated")]
    try:
        from . import compose
    except ImportError as e:
        return [Check("compose-policy", "NOT_RUN", f"compose module unavailable: {e}")]
    ok, why = compose.docker_available()
    if not ok:
        return [Check("compose-policy", "NOT_RUN", f"docker unavailable: {why}")]
    pname = compose.project_name(ctx.project, ctx.run_id)
    env = {**_base_env(ctx), "COMPOSE_PROJECT_NAME": pname}
    cfg = compose.load_config(ctx.worktree, ctx.config["stack"].get("file", "compose.yaml"), pname, env)
    protected = _other_projects(ctx.project)
    cfg.setdefault("name", pname)
    v = compose.policy_violations(cfg, str(ctx.worktree), protected)
    chk = Check("compose-policy", "FAIL" if v else "PASS",
                f"{len(v)} compose policy violation(s)" if v else "compose policy ok", list(v))
    ctx._compose.update(pname=pname, env=env, module=compose)
    return [chk]


def _verify_argv(ctx: GateContext) -> list[str]:
    argv = shlex.split(ctx.config["verify"]["command"].replace("{milestone}", ctx.verify_id))
    if "/" in argv[0] and not argv[0].startswith("/"):
        argv[0] = str(ctx.worktree / argv[0])
    return argv


def _run_verify(ctx: GateContext, env: dict | None) -> Check:
    t0 = time.monotonic()
    argv = _verify_argv(ctx)
    note = ["not isolated: ran on the host"] if ctx.host else []
    if "/" in argv[0] and not Path(argv[0]).exists():
        return Check("verify", "NOT_RUN", f"verify command not found: {ctx.config['verify']['command'].split()[0]}",
                     note)
    log = ctx.out_dir / "verify.log"
    res = run_process(argv, ctx.worktree, ctx.config["verify"]["timeout_min"] * 60, log, env=env)
    dur = time.monotonic() - t0
    label = " ".join(shlex.quote(os.path.relpath(a, ctx.worktree) if a.startswith(str(ctx.worktree)) else a)
                     for a in argv)
    if res.launch_error:
        return Check("verify", "FAIL", f"verify could not start: {res.launch_error}", note, str(log), dur)
    if res.timed_out:
        return Check("verify", "FAIL", f"{label} timed out", note, str(log), dur)
    if res.returncode != 0:
        return Check("verify", "FAIL", f"{label} failed rc={res.returncode}", note, str(log), dur)
    return Check("verify", "PASS", f"{label} passed", note, str(log), dur)


def _m0_structure(ctx: GateContext) -> Check:
    from .models import ConfigError, load_plan
    t0 = time.monotonic()
    wt, problems = ctx.worktree, []
    for f in ("SPEC.md", "scripts/verify.sh", ".harness/plan.json"):
        if not (wt / f).exists():
            problems.append(f"missing {f}")
    v = wt / "scripts/verify.sh"
    if v.exists():
        if not os.access(v, os.X_OK):
            problems.append("scripts/verify.sh is not executable")
        r = subprocess.run(["bash", "-n", str(v)], capture_output=True, text=True)
        if r.returncode:
            problems.append("verify.sh syntax error: " + r.stderr[-300:])
    if (wt / ".harness/plan.json").exists():
        try:
            plan = load_plan(wt)
            if not plan["frozen"]:
                problems.append("plan.frozen is empty")
            for p in plan["frozen"]:
                if not (wt / p).exists():
                    problems.append(f"frozen path does not exist: {p}")
        except ConfigError as e:
            problems.append(f"plan invalid: {e}")
    if problems:
        return Check("m0-structure", "FAIL", "M0 contract incomplete", problems,
                     duration_s=time.monotonic() - t0)
    return Check("m0-structure", "PASS", "M0 contract structure ok", duration_s=time.monotonic() - t0)


def _verify(ctx: GateContext) -> list[Check]:
    if ctx.milestone["id"] == "M0":
        return [_m0_structure(ctx)]
    if ctx.host or not ctx._compose:
        if not ctx.host:
            return [Check("verify", "NOT_RUN", "compose stack unavailable (policy check did not run)")]
        return [_run_verify(ctx, _base_env(ctx))]
    compose = ctx._compose["module"]
    t0 = time.monotonic()
    session = compose.ComposeSession(ctx.worktree, ctx.config["stack"].get("file", "compose.yaml"),
                                     ctx._compose["pname"], ctx._compose["env"],
                                     ctx.out_dir / "compose-artifacts",
                                     ctx.config["verify"]["timeout_min"] * 60)
    # Holdouts need the same live stack, so they run inside the session right after a green
    # verify; _holdout() then returns the cached result. Teardown always happens on exit.
    with session:
        chk = _run_verify(ctx, ctx._compose["env"])
        if chk.status == "PASS":
            try:
                ctx._compose["holdout_check"] = _run_holdouts(ctx, ctx._compose["env"])
            except Exception as e:  # crashed holdout run is a failure, never a pass
                ctx._compose["holdout_check"] = Check("holdout", "FAIL",
                                                      f"holdout run crashed: {type(e).__name__}: {e}")
    td = compose.teardown_check(session)
    chk.duration_s = time.monotonic() - t0
    return [chk, td]


def _run_holdouts(ctx: GateContext, env: dict) -> Check:
    return holdout.run_holdouts(project=ctx.project, worktree=ctx.worktree,
                                milestone_id=ctx.verify_id, cfg=ctx.config, out_dir=ctx.out_dir,
                                env=env)


def _holdout(ctx: GateContext) -> list[Check]:
    if ctx.milestone["id"] == "M0":
        return [Check("holdout", "NOT_RUN", "no holdouts during M0")]
    if "holdout_check" in ctx._compose:
        return [ctx._compose["holdout_check"]]
    if not ctx.host:
        return [Check("holdout", "NOT_RUN", "stack was not running")]
    return [_run_holdouts(ctx, _base_env(ctx))]


def _audit(ctx: GateContext) -> list[Check]:
    try:
        from . import audit_diff
    except ImportError as e:
        return [Check("audit-diff", "NOT_RUN", f"audit_diff module unavailable: {e}")]
    allow = list(ctx.milestone.get("allowed_paths", [])) + IMPLICIT_ALLOWED
    res = audit_diff.audit(ctx.worktree, base=ctx.base, allow_paths=allow)
    return [audit_diff.to_check(res)]


_FUNCS = {"scope": _scope, "frozen": _frozen, "hygiene": _hygiene, "compose-policy": _policy,
          "verify": _verify, "holdout": _holdout, "audit-diff": _audit}


# ------------------------------------------------------------------ driver
def feedback_from_checks(checks: list[Check], tail_lines: int = 60) -> str:
    """Scrubbed text for the builder: failing checks, details and a log tail.
    Holdout raw logs are never included (their Check carries scrubbed details only)."""
    parts = []
    for c in checks:
        if c.status == "PASS" or (c.status == "NOT_RUN" and c.id not in TEST_CHECKS):
            continue
        parts.append(f"[{c.id}] {c.status}: {c.summary.removeprefix(HUMAN_PREFIX).strip()}")
        parts += [f"  - {d}" for d in c.details[:20]]
        if c.log and c.id != "holdout":
            t = tail(c.log, tail_lines)
            if t:
                parts.append("  log tail:\n" + "\n".join("    " + ln for ln in t.splitlines()))
    return "\n".join(parts)


def run_gate(ctx: GateContext) -> tuple[bool, list[Check]]:
    ctx.out_dir = Path(ctx.out_dir)
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []
    start = workspace.candidate_hash(ctx.worktree)
    failed = False
    for name in STEPS:
        if failed:
            checks.append(Check(name, "NOT_RUN", "skipped: earlier check failed"))
            continue
        try:
            res = _FUNCS[name](ctx)
        except Exception as e:  # a crashed check is a failure, never a pass
            res = [Check(name, "FAIL", f"check crashed: {type(e).__name__}: {e}",
                         traceback.format_exc().splitlines()[-4:])]
        checks += res
        failed = any(c.status == "FAIL" for c in res)
    if failed:
        checks.append(Check("candidate", "NOT_RUN", "skipped: earlier check failed"))
    else:
        end = workspace.candidate_hash(ctx.worktree)
        if end != start:
            checks.append(Check("candidate", "FAIL", "candidate changed while the gate ran",
                                [f"start {start[:12]}", f"end {end[:12]}"]))
            failed = True
        else:
            checks.append(Check("candidate", "PASS", f"candidate {end[:12]} unchanged", [end]))
    ok = not failed
    if ok and ctx.config["verify"]["require_tests"]:
        if not any(c.id in TEST_CHECKS and c.status == "PASS" for c in checks):
            checks.append(Check("require-tests", "FAIL",
                                "require_tests is on but no test check actually ran"))
            ok = False
    write_json(ctx.out_dir / "gate.json", {
        "milestone": ctx.milestone["id"], "ok": ok, "at": now(),
        "stack": ctx.config["stack"]["type"],
        "not_isolated": ctx.host,
        "candidate": start,
        "checks": [c.to_dict() for c in checks]})
    return ok, checks
