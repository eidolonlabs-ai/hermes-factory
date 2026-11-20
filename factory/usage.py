"""Best-effort accounting; unknown usage is not zero usage."""
from __future__ import annotations

import json
import math
import os
import stat
import subprocess
from functools import lru_cache
from pathlib import Path

TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write")
COST_BASIS = "API-rate estimate, not billed spend"


def token_counts(values: dict) -> dict[str, int]:
    return {k: v for k in TOKEN_FIELDS if type(v := values.get(k)) is int and v >= 0}


def add_tokens(total: dict, tokens: dict) -> None:
    for key, count in token_counts(tokens).items():
        total[key] = total.get(key, 0) + count


def cost_amount(value) -> float | None:
    try:
        return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


@lru_cache(maxsize=8)
def supports_hermes_usage(executable: str) -> bool:
    """Keep running on older Hermes releases without the usage-file option."""
    try:
        result = subprocess.run([executable, "--help"], capture_output=True, text=True,
                                timeout=5, stdin=subprocess.DEVNULL)
        return result.returncode == 0 and "--usage-file" in result.stdout
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return False


def hermes_usage(path: Path) -> dict:
    limit = 1024 * 1024
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                return {}
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(limit + 1)
        finally:
            os.close(fd)
        if len(data) > limit:
            return {}
        report = json.loads(data)
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(report, dict):
        return {}
    tokens = token_counts({k: report.get(f"{k}_tokens") for k in TOKEN_FIELDS})
    aux = report.get("auxiliary")
    if isinstance(aux, dict):
        add_tokens(tokens, {k: aux.get(f"{k}_tokens") for k in TOKEN_FIELDS})
    total = report.get("total_including_auxiliary")
    cost = (total if isinstance(total, dict) else report).get("estimated_cost_usd")
    return {"tokens": tokens, "cost_usd": cost_amount(cost)}
