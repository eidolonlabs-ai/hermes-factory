"""Locks, git worktrees, candidate hash, fast-forward merge."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import state


class WorkspaceError(ValueError):
    pass


def git(repo: Path | str, *args: str, check: bool = True, timeout: int = 120) -> str:
    env = dict(os.environ)
    for k, v in (("GIT_AUTHOR_NAME", "factory"), ("GIT_AUTHOR_EMAIL", "factory@localhost"),
                 ("GIT_COMMITTER_NAME", "factory"), ("GIT_COMMITTER_EMAIL", "factory@localhost")):
        env.setdefault(k, v)
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout, env=env)
    if check and p.returncode:
        raise WorkspaceError(f"git {' '.join(args[:3])} failed: "
                             + p.stderr.decode(errors="replace").strip())
    out = p.stdout.decode(errors="surrogateescape")
    return out if "-z" in args else out.rstrip("\n")


# ---------------------------------------------------------------- locks
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@dataclass
class Lock:
    path: Path

    def release(self) -> None:
        self.path.unlink(missing_ok=True)


def acquire_lock(project: str, milestone: str, run_id: str) -> Lock:
    """Per-(project, milestone) lock via O_EXCL. A lock whose owner pid is dead is taken over."""
    d = state.locks_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{milestone}.lock"
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            owner = None
            try:
                for tok in path.read_text().split():
                    if tok.startswith("pid="):
                        owner = int(tok[4:])
            except (OSError, ValueError):
                pass
            if owner and _pid_alive(owner):
                raise WorkspaceError(f"milestone {milestone} is locked by pid {owner} ({path})")
            path.unlink(missing_ok=True)  # stale
            continue
        with os.fdopen(fd, "w") as f:
            f.write(f"pid={os.getpid()} run={run_id}\n")
        return Lock(path)
    raise WorkspaceError(f"could not acquire lock {path}")


# ---------------------------------------------------------------- worktrees
@dataclass
class Workspace:
    path: Path
    repo: Path
    base: str
    base_branch: str
    branch: str


def current_branch(repo: Path | str) -> str:
    b = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if b == "HEAD":
        raise WorkspaceError("repository is on a detached HEAD")
    return b


def is_clean(repo: Path | str) -> bool:
    return not git(repo, "status", "--porcelain")


def create_worktree(repo: Path, project: str, milestone: str, run_id: str) -> Workspace:
    if not is_clean(repo):
        raise WorkspaceError("repository must be clean (including untracked files) to start a run")
    base_branch = current_branch(repo)
    base = git(repo, "rev-parse", "HEAD")
    path = state.worktrees_dir(project) / run_id
    path.parent.mkdir(parents=True, exist_ok=True)
    branch = f"factory/{milestone}/{run_id}"
    git(repo, "worktree", "add", "-b", branch, str(path), base)
    return Workspace(path, Path(repo), base, base_branch, branch)


def attach_worktree(repo: Path, path: Path, branch: str, base: str, base_branch: str) -> Workspace:
    return Workspace(Path(path), Path(repo), base, base_branch, branch)


def remove_worktree(ws: Workspace, delete_branch: bool = False) -> None:
    git(ws.repo, "worktree", "remove", "--force", str(ws.path), check=False)
    if ws.path.exists():
        shutil.rmtree(ws.path, ignore_errors=True)
    git(ws.repo, "worktree", "prune", check=False)
    if delete_branch:
        git(ws.repo, "branch", "-D", ws.branch, check=False)


def commit_leftovers(path: Path, message: str) -> bool:
    if not git(path, "status", "--porcelain"):
        return False
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return True


def head_sha(path: Path | str) -> str:
    return git(path, "rev-parse", "HEAD")


def changed_paths(path: Path, base: str) -> list[str]:
    """Paths changed vs base: committed + working tree + untracked (not ignored)."""
    tracked = git(path, "diff", "--name-only", "--no-renames", "-z", base, "--")
    untracked = git(path, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(set(filter(None, (tracked + "\0" + untracked).split("\0"))))


def changed_status(path: Path, base: str) -> dict[str, str]:
    """path -> 'A' | 'M' | 'D' vs base (untracked counted as A)."""
    out: dict[str, str] = {}
    raw = git(path, "diff", "--name-status", "--no-renames", "-z", base, "--")
    parts = raw.split("\0")
    for i in range(0, len(parts) - 1, 2):
        out[parts[i + 1]] = parts[i][:1]
    for p in filter(None, git(path, "ls-files", "--others", "--exclude-standard", "-z").split("\0")):
        out[p] = "A"
    return out


def candidate_hash(path: Path) -> str:
    """sha256 over HEAD, diffs, and every non-ignored file's mode and content."""
    path = Path(path)
    h = hashlib.sha256()
    for args in (("rev-parse", "HEAD"), ("diff", "--binary", "HEAD", "--"),
                 ("diff", "--cached", "--binary", "--")):
        h.update(git(path, *args).encode(errors="surrogateescape"))
        h.update(b"\0")
    files = git(path, "ls-files", "-c", "-o", "--exclude-standard", "-z")
    for name in sorted(set(filter(None, files.split("\0")))):
        p = path / name
        h.update(name.encode(errors="surrogateescape") + b"\0")
        if p.is_symlink():
            h.update(b"link:" + os.readlink(p).encode(errors="surrogateescape"))
        elif p.is_file():
            h.update(str(p.stat().st_mode & 0o777).encode() + b":")
            with p.open("rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
        elif not p.exists():
            h.update(b"deleted")
        h.update(b"\0")
    return h.hexdigest()


def merge_ff(ws: Workspace) -> tuple[bool, str]:
    """Fast-forward the base branch to the workspace branch, only if it has not moved."""
    repo = ws.repo
    try:
        if current_branch(repo) != ws.base_branch:
            return False, f"main checkout is no longer on {ws.base_branch}"
        if head_sha(repo) != ws.base:
            return False, f"{ws.base_branch} moved since the run started; rebase needed"
        if not is_clean(repo):
            return False, "main checkout has uncommitted changes"
        git(repo, "merge", "--ff-only", ws.branch)
    except WorkspaceError as e:
        return False, str(e)
    return True, head_sha(repo)
