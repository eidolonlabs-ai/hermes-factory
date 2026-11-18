"""Atomic evidence writes and small log helpers. Local audit data, not an attestation."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path | str, data) -> None:
    """Atomic JSON write (temp file + fsync + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, allow_nan=False, default=str)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def write_result(run_dir: Path | str, result: dict) -> None:
    write_json(Path(run_dir) / "result.json", result)


def read_json(path: Path | str, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def tail(path: Path | str | None, n: int = 60) -> str:
    if not path:
        return ""
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except (FileNotFoundError, IsADirectoryError):
        return ""
    return "\n".join(lines[-n:])


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
