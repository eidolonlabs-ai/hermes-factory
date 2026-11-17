"""Hygiene gate step: no tracked secrets/keys, and a present .env must be git-ignored.

Port of the hygiene part of agy-software-factory verify.js.
"""
from __future__ import annotations

import os
import subprocess
import time

from .types import Check

ALLOWED_ENV_TEMPLATES = {".env.example", ".env.sample", ".env.template", ".env.test"}
PRIVATE_KEY_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)


def _in_work_tree(root: str) -> bool:
    try:
        r = _git(["rev-parse", "--is-inside-work-tree"], root)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def is_sensitive_path(rel: str) -> bool:
    base = rel.replace("\\", "/").rsplit("/", 1)[-1]
    if base in ALLOWED_ENV_TEMPLATES:
        return False
    if base == ".env" or base.startswith(".env."):
        return True
    if base in PRIVATE_KEY_NAMES:
        return True
    return base.endswith(".pem") or base.endswith(".key")


def _gitignore_covers_env(path: str) -> bool:
    if not os.path.isfile(path):
        return False
    ignored = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh.read().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line in (".env", "/.env", ".env*", "/.env*", "*.env", "**/.env"):
                ignored = True
            elif line in ("!.env", "!/.env"):
                ignored = False
    return ignored


def check_hygiene(root: str) -> Check:
    start = time.monotonic()
    details: list[str] = []
    in_git = _in_work_tree(root)

    if os.path.isfile(os.path.join(root, ".env")):
        ignored = False
        if in_git:
            ignored = _git(["check-ignore", "-q", "--no-index", ".env"], root).returncode == 0
        else:
            ignored = _gitignore_covers_env(os.path.join(root, ".gitignore"))
        if not ignored:
            details.append(".env exists but is not ignored by git")

    if in_git:
        r = _git(["ls-files", "-z"], root)
        if r.returncode == 0:
            for rel in r.stdout.split("\0"):
                if rel and is_sensitive_path(rel):
                    details.append(f"tracked sensitive file: {rel}")

    dur = time.monotonic() - start
    if details:
        return Check("hygiene", "FAIL", f"{len(details)} hygiene issue(s)", details, duration_s=dur)
    return Check("hygiene", "PASS", "workspace hygiene check passed", [], duration_s=dur)
