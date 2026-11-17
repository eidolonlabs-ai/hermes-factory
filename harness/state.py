"""Harness state lives OUTSIDE every repo: $HARNESS_HOME (default ~/.hermes/harness)."""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

from .evidence import now, read_json, write_json


def home() -> Path:
    h = os.environ.get("HARNESS_HOME")
    p = Path(h).expanduser() if h else Path.home() / ".hermes" / "harness"
    p.mkdir(parents=True, exist_ok=True)
    return p


def state_path(project: str) -> Path:
    return home() / "state" / f"{project}.json"


def runs_dir(project: str) -> Path:
    return home() / "runs" / project


def run_dir(project: str, run_id: str) -> Path:
    return runs_dir(project) / run_id


def worktrees_dir(project: str) -> Path:
    return home() / "worktrees" / project


def holdout_store(project: str) -> Path:
    return home() / "holdout" / project


def locks_dir(project: str) -> Path:
    return home() / "locks" / project


def new_state(project: str, repo: str) -> dict:
    return {"project": project, "repo": repo, "created": now(), "freeze_sha": None,
            "frozen": [], "holdout_files": [], "interventions": [], "runs": [],
            "extra_milestones": {}, "done": {}, "cost_usd": 0.0}


def exists(project: str) -> bool:
    return state_path(project).exists()


def load_state(project: str) -> dict:
    s = read_json(state_path(project))
    if s is None:
        raise KeyError(f"unknown project '{project}' (no {state_path(project)}); run `harness init`")
    return s


@contextmanager
def _flock(project: str):
    p = state_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def save_state(state: dict) -> None:
    with _flock(state["project"]):
        write_json(state_path(state["project"]), state)


def update_state(project: str, fn) -> dict:
    """Read-modify-write under a file lock. fn(state) mutates in place."""
    with _flock(project):
        s = load_state(project)
        fn(s)
        write_json(state_path(project), s)
        return s


def init_project(project: str, repo: str, force: bool = False) -> dict:
    if exists(project) and not force:
        s = load_state(project)
        if s["repo"] != repo:
            raise ValueError(f"project '{project}' already registered for {s['repo']}")
        return s
    s = new_state(project, repo)
    save_state(s)
    return s


def find_project_by_repo(repo: str) -> str | None:
    d = home() / "state"
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            s = read_json(f)
            if s and s.get("repo") == repo:
                return s["project"]
    return None


def all_projects() -> list[str]:
    d = home() / "state"
    return sorted(f.stem for f in d.glob("*.json")) if d.is_dir() else []


def add_note(project: str, text: str) -> int:
    def f(s):
        s["interventions"].append({"at": now(), "note": text})
    return len(update_state(project, f)["interventions"])
