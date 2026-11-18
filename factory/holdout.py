"""Holdout tests: moved out of the repo at freeze; copied in only while gating; scrubbed."""
from __future__ import annotations

import re
import shlex
import shutil
import time
from pathlib import Path

from .evidence import now
from .models import load_plan
from .process import run_process
from .types import Check
from . import state, workspace

DEFAULT_HOLDOUT_DIR = "tests/holdout"


def _expand(root: Path, entries: list[str]) -> list[str]:
    out = set()
    for e in entries:
        p = root / e.rstrip("/")
        if p.is_file():
            out.add(e.rstrip("/"))
        elif p.is_dir():
            out.update(f.relative_to(root).as_posix() for f in p.rglob("*") if f.is_file())
    return sorted(out)


def freeze(repo: Path, project: str, force: bool = False) -> dict:
    """Freeze: record sha + frozen list; move holdouts to the store and commit the removal."""
    repo = Path(repo)
    st = state.load_state(project)
    if st.get("freeze_sha") and not force:
        raise ValueError(f"already frozen at {st['freeze_sha'][:10]} (use --force to re-freeze)")
    if not workspace.is_clean(repo):
        raise ValueError("repo has uncommitted changes; commit before freezing")
    plan = load_plan(repo)
    if not plan["frozen"]:
        raise ValueError("plan.json has no 'frozen' list")
    frozen = sorted(set(plan["frozen"] + [".factory/plan.json"]))
    missing = [p for p in frozen if not (repo / p).exists()]
    if missing:
        raise ValueError("frozen paths do not exist: " + ", ".join(missing))
    store = state.holdout_store(project)
    moved = _expand(repo, [DEFAULT_HOLDOUT_DIR] + plan["holdout"])
    for rel in moved:
        dst = store / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(repo / rel), str(dst))
    for d in sorted({(repo / r).parent for r in moved}, key=lambda x: -len(x.parts)):
        while d != repo and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent
    if moved:
        workspace.git(repo, "add", "-A")
        workspace.git(repo, "commit", "-q", "-m", "chore(factory): move holdouts out of the repo")
    sha = workspace.head_sha(repo)

    def upd(s):
        s["freeze_sha"], s["frozen"], s["frozen_at"] = sha, frozen, now()
        s["holdout_files"] = sorted(set(s.get("holdout_files", [])) | set(moved))
    state.update_state(project, upd)
    return {"freeze_sha": sha, "frozen": frozen, "holdouts_moved": len(moved)}


def stored_files(project: str) -> list[str]:
    store = state.holdout_store(project)
    if not store.is_dir():
        return []
    return sorted(f.relative_to(store).as_posix() for f in store.rglob("*") if f.is_file())


def stage_in(project: str, worktree: Path) -> list[Path]:
    """Copy stored holdouts into the worktree. Returns created paths for cleanup."""
    created = []
    store = state.holdout_store(project)
    for rel in stored_files(project):
        dst = Path(worktree) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(store / rel, dst)
        created.append(dst)
    return created


def remove(worktree: Path, created: list[Path]) -> None:
    worktree = Path(worktree)
    for p in created:
        p.unlink(missing_ok=True)
    for p in sorted({q.parent for q in created}, key=lambda x: -len(x.parts)):
        while p != worktree and p.is_dir():
            try:
                p.rmdir()
            except OSError:
                break
            p = p.parent


_PY_FAIL = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?\s*$")
_PY_VERBOSE = re.compile(r"^(\S+::\S+)\s+(?:FAILED|ERROR)\b")
_PW_FAIL = re.compile(r"^\s*\d+\)\s+(.+?)\s*[─-]*\s*$")
_FAILED_N = re.compile(r"(\d+)\s+failed")
_PASSED_N = re.compile(r"(\d+)\s+passed")
_MAX = 200


def scrub_output(text: str, mode: str = "names_and_messages") -> tuple[str, list[str]]:
    """Reduce raw holdout output to (summary, details): test ids and assertion messages
    (or counts only). Never returns source lines. Handles pytest and playwright formats."""
    lines = text.splitlines()
    found: list[tuple[str, str]] = []
    seen = set()
    for i, line in enumerate(lines):
        tid = msg = None
        m = _PY_FAIL.match(line)
        if m:
            tid, msg = m.group(1), m.group(2) or ""
        else:
            m = _PY_VERBOSE.match(line)
            if m:
                tid, msg = m.group(1), ""
            else:
                m = _PW_FAIL.match(line)
                if m and ("›" in m.group(1) or "::" in m.group(1)):
                    tid = m.group(1)
                    for nxt in lines[i + 1:i + 8]:
                        s = nxt.strip()
                        if s.startswith("Error:") or s.startswith("AssertionError"):
                            msg = s
                            break
        if tid and tid not in seen:
            seen.add(tid)
            found.append((tid[:_MAX], re.sub(r"\s+", " ", msg or "")[:_MAX]))
    failed = passed = None
    for line in lines:
        f, p = _FAILED_N.search(line), _PASSED_N.search(line)
        if f:
            failed = int(f.group(1))
        if p:
            passed = int(p.group(1))
    n = failed if failed is not None else len(found)
    counts = f"{n} failed" + (f", {passed} passed" if passed is not None else "")
    if not found and failed is None:
        return "holdout command failed (output withheld)", []
    summary = f"holdouts: {counts}"
    if mode == "counts_only":
        return summary, []
    return summary, [f"{tid}: {msg}" if msg else tid for tid, msg in found]


def run_holdouts(*, project: str, worktree: Path, milestone_id: str, cfg: dict, out_dir: Path,
                 env: dict | None = None) -> Check:
    t0 = time.monotonic()
    h = cfg["holdout"]
    if not h["enabled"]:
        return Check("holdout", "NOT_RUN", "holdouts disabled")
    if not stored_files(project):
        return Check("holdout", "NOT_RUN", "no holdout tests stored for this project")
    argv = shlex.split(h["command"].replace("{milestone}", milestone_id))
    if "/" in argv[0] and not argv[0].startswith("/"):
        argv[0] = str(Path(worktree) / argv[0])
    if not Path(argv[0]).exists() and "/" in argv[0]:
        return Check("holdout", "NOT_RUN", f"holdout command not found: {h['command'].split()[0]}")
    created = stage_in(project, worktree)
    raw = Path(out_dir) / "holdout.raw.log"  # never shown to builders
    try:
        res = run_process(argv, worktree, cfg["verify"]["timeout_min"] * 60, raw, env=env)
    finally:
        remove(worktree, created)
    dur = time.monotonic() - t0
    if res.launch_error:
        return Check("holdout", "FAIL", "holdout command could not start", duration_s=dur)
    if res.timed_out:
        return Check("holdout", "FAIL", "holdout command timed out", duration_s=dur)
    if res.returncode == 0:
        return Check("holdout", "PASS", "holdouts passed", duration_s=dur)
    summary, details = scrub_output(raw.read_text(errors="replace"), h["feedback"])
    return Check("holdout", "FAIL", summary, details, None, dur)
