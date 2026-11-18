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


def _ensure_safe_subpath(root: Path, rel: str) -> Path:
    """Verify `rel` is a safe repo-relative path with no symlinks along any component."""
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError(f"unsafe holdout path: {rel}")
    root_real = root.resolve()
    cur = root
    for part in p.parts:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError(f"symlink not allowed in holdout path: {cur.relative_to(root)}")
    resolved = cur.resolve()
    try:
        resolved.relative_to(root_real)
    except ValueError:
        raise ValueError(f"holdout path escapes root: {rel}") from None
    return cur


def _prune_empty_dirs(stop_at: Path, dirs) -> None:
    for d in sorted(set(dirs), key=lambda x: -len(x.parts)):
        while d != stop_at and d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
            except OSError:
                break
            d = d.parent


def _expand(root: Path, entries: list[str]) -> list[str]:
    out = set()
    for e in entries:
        p = root / e.rstrip("/")
        if p.is_symlink():
            raise ValueError(f"holdout entry must not be a symlink: {e}")
        if p.is_file():
            out.add(e.rstrip("/"))
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_symlink():
                    raise ValueError(f"holdout tree must not contain symlinks: {f.relative_to(root)}")
                if f.is_file():
                    out.add(f.relative_to(root).as_posix())
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
    for p in frozen:
        _ensure_safe_subpath(repo, p)
    store = state.holdout_store(project)
    moved = _expand(repo, [DEFAULT_HOLDOUT_DIR] + plan["holdout"])
    for rel in moved:
        _ensure_safe_subpath(repo, rel)
    if force and store.is_dir():
        moved_set = set(moved)
        pruned_dirs = []
        for old in stored_files(project):
            keep = (old in moved_set) if moved else (
                old.startswith(DEFAULT_HOLDOUT_DIR + "/")
                or any(old == p.rstrip("/") or old.startswith(p.rstrip("/") + "/") for p in plan["holdout"])
            )
            if not keep:
                target = store / old
                target.unlink(missing_ok=True)
                pruned_dirs.append(target.parent)
        _prune_empty_dirs(store, pruned_dirs)
    for rel in moved:
        dst = store / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(repo / rel), str(dst))
    _prune_empty_dirs(repo, [(repo / r).parent for r in moved])
    if moved:
        workspace.git(repo, "add", "-A")
        workspace.git(repo, "commit", "-q", "-m", "chore(factory): move holdouts out of the repo")
    sha = workspace.head_sha(repo)
    current_holdouts = stored_files(project)

    def upd(s):
        s["freeze_sha"], s["frozen"], s["frozen_at"] = sha, frozen, now()
        s["holdout_files"] = current_holdouts
    state.update_state(project, upd)
    return {"freeze_sha": sha, "frozen": frozen, "holdouts_moved": len(moved)}


def stored_files(project: str) -> list[str]:
    store = state.holdout_store(project)
    if not store.is_dir():
        return []
    return sorted(f.relative_to(store).as_posix() for f in store.rglob("*") if f.is_file() and not f.is_symlink())


def stage_in(project: str, worktree: Path) -> list[Path]:
    """Copy stored holdouts into the worktree. Fails on symlinks or pre-existing holdout files."""
    worktree = Path(worktree)
    holdout_dir = worktree / DEFAULT_HOLDOUT_DIR
    if holdout_dir.is_symlink():
        raise ValueError(f"symlink not allowed at {DEFAULT_HOLDOUT_DIR}")
    if holdout_dir.exists() and any(holdout_dir.rglob("*")):
        raise ValueError(f"untrusted pre-existing entries under {DEFAULT_HOLDOUT_DIR}/")
    created: list[Path] = []
    store = state.holdout_store(project)
    try:
        for rel in stored_files(project):
            src = store / rel
            if src.is_symlink():
                raise ValueError(f"holdout store contains symlink: {rel}")
            dst = _ensure_safe_subpath(worktree, rel)
            if dst.exists() or dst.is_symlink():
                raise ValueError(f"holdout staging collision with worktree path: {rel}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            created.append(dst)
    except Exception:
        remove(worktree, created)
        raise
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
    try:
        created = stage_in(project, worktree)
    except ValueError as e:
        return Check("holdout", "FAIL", f"holdout isolation violated: {e}",
                     duration_s=time.monotonic() - t0)
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
