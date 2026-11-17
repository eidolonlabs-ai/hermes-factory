"""Shared result types. Every module that produces a check result uses these.

Kept tiny on purpose so independently written modules agree on shapes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Status = Literal["PASS", "FAIL", "NOT_RUN"]
DecisionKind = Literal["allow", "deny", "ask"]


@dataclass
class Check:
    """One gate step / check. NOT_RUN is never PASS (CONTRACT.md §3)."""

    id: str                      # e.g. "scope", "frozen", "hygiene", "compose-policy", "verify"
    status: Status
    summary: str = ""            # one line, safe to show to a builder
    details: list[str] = field(default_factory=list)   # short items (paths, findings)
    log: str | None = None       # path to a full log on disk, if any
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    """Guard decision for one tool call (CONTRACT.md §8)."""

    decision: DecisionKind
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GuardContext:
    """What the guard needs to know about the project. Paths are repo-relative POSIX."""

    root: str                                  # absolute repo/worktree root
    control_dir: str = ".harness/"
    frozen: list[str] = field(default_factory=list)
    holdout_markers: list[str] = field(default_factory=lambda: ["holdout/", ".holdout."])
    unattended: bool = True                    # "ask" is reported as-is; adapters map it
    contract_phase: bool = False               # M0: architect/reviewer author plan.json + holdouts
