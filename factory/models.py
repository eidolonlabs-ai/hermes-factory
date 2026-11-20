"""Strict loading and validation of .factory/config.json and .factory/plan.json (DESIGN §6)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

ENGINE_NAMES = ("codex", "claude", "hermes", "agy", "fake")
MERGE_POLICIES = ("ff", "pr", "human")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MILESTONE_RE = re.compile(r"^M\d+$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id) or ".." in run_id:
        raise ConfigError(f"invalid run_id {run_id!r}: must match [A-Za-z0-9][A-Za-z0-9._-]* without '..'")
    return run_id


class ConfigError(ValueError):
    """Invalid config.json / plan.json."""


DEFAULT_CONFIG: dict = {
    "project": None,
    "verify": {"command": "scripts/verify.sh {milestone}", "timeout_min": 40, "require_tests": True},
    "holdout": {"enabled": True, "command": "scripts/holdout.sh {milestone}",
                "feedback": "names_and_messages"},
    "roles": {"architect": "claude", "backend": "codex", "ui": "claude", "review": "cross"},
    "cross": None,  # absent/null keeps legacy defaults; an explicit map is authoritative
    "engines": {"claude": {"model": "opus", "max_usd_per_run": 15},
                "codex": {"effort": "high"},
                "hermes": {"profile": "factory-coder"}},
    "budgets": {"attempts": 3, "engine_timeout_min": 90, "run_timeout_min": 240,
                "review_rounds": 2, "project_max_usd": 150},
    "protected": ["tests/", "scripts/verify.sh", "scripts/holdout.sh", "contracts/", ".factory/", "AGENTS.md"],
    "stack": {"type": "compose", "file": "compose.yaml"},
    "merge": "ff",
    "notify": "hermes",
}

_ENGINE_KEYS = {"claude": {"model", "effort", "max_usd_per_run"},
                "codex": {"model", "effort", "sandbox"},
                "hermes": {"profile"}, "agy": set(), "fake": set()}


def _obj(v, name, allowed):
    if not isinstance(v, dict):
        raise ConfigError(f"{name} must be an object")
    extra = set(v) - set(allowed)
    if extra:
        raise ConfigError(f"{name}: unknown keys {sorted(extra)}")
    return v


def _str(v, name):
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"{name} must be a non-empty string")
    return v


def _bool(v, name):
    if not isinstance(v, bool):
        raise ConfigError(f"{name} must be a boolean")
    return v


def _num(v, name, integer=False):
    ok = isinstance(v, int) if integer else isinstance(v, (int, float))
    if isinstance(v, bool) or not ok or v <= 0:
        raise ConfigError(f"{name} must be a positive {'integer' if integer else 'number'}")
    return v


def _strlist(v, name, allow_empty=True):
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise ConfigError(f"{name} must be a list of non-empty strings")
    if not allow_empty and not v:
        raise ConfigError(f"{name} must not be empty")
    return v


def safe_relpath(p: str, name: str) -> str:
    if p.startswith("/") or ".." in Path(p).parts or "\\" in p:
        raise ConfigError(f"{name}: path must be relative and inside the repo: {p!r}")
    return p


def normalize_allow_paths(allow_paths) -> list[str]:
    if not allow_paths:
        return []
    raw = allow_paths.split(",") if isinstance(allow_paths, str) else list(allow_paths)
    out = []
    for p in raw:
        p = str(p).strip().replace("\\", "/")
        if p.startswith("./"):
            p = p[2:]
        if p:
            out.append(p)
    return out


def glob_to_regex(pattern: str) -> re.Pattern:
    out = "^"
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i + 1:i + 2] == "*":
                if pattern[i + 2:i + 3] == "/":
                    out += "(?:.+/)?"
                    i += 2
                else:
                    out += ".*"
                    i += 1
            else:
                out += "[^/]*"
        elif ch == "?":
            out += "[^/]"
        else:
            out += re.escape(ch)
        i += 1
    return re.compile(out + "$", re.S)


def matches_allowed_path(path: str, patterns) -> bool:
    norm = path.replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    for raw in patterns:
        pat = str(raw).strip().replace("\\", "/")
        if pat.startswith("./"):
            pat = pat[2:]
        if not pat:
            continue
        if pat in (".", "*", "**"):
            return True
        if pat.endswith("/**") or pat.endswith("/*"):
            prefix = re.sub(r"/+$", "", re.sub(r"/\*+$", "", pat))
            if norm == prefix or norm.startswith(prefix + "/"):
                return True
        if "*" in pat or "?" in pat:
            if glob_to_regex(pat).match(norm):
                return True
            continue
        clean = pat.rstrip("/")
        if norm == clean or norm.startswith(clean + "/"):
            return True
    return False


def validate_config(raw: dict) -> dict:
    """Merge defaults and validate strictly. Returns a new normalised dict."""
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    _obj(raw, "config", DEFAULT_CONFIG)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in raw.items():
        if isinstance(cfg[k], dict) and k != "engines":
            if not isinstance(v, dict):
                raise ConfigError(f"{k} must be an object")
            _obj(v, k, cfg[k] if k != "stack" else {"type", "file", "reason"})
            cfg[k].update(v)
        elif k == "engines":
            _obj(v, "engines", ENGINE_NAMES)
            for en, ev in v.items():
                _obj(ev, f"engines.{en}", _ENGINE_KEYS[en])
                cfg["engines"].setdefault(en, {}).update(ev)
        else:
            cfg[k] = v
    p = cfg["project"]
    if not isinstance(p, str) or not PROJECT_RE.match(p):
        raise ConfigError("project must match [A-Za-z0-9][A-Za-z0-9._-]*")
    v = cfg["verify"]
    _str(v["command"], "verify.command")
    _num(v["timeout_min"], "verify.timeout_min")
    _bool(v["require_tests"], "verify.require_tests")
    h = cfg["holdout"]
    _bool(h["enabled"], "holdout.enabled")
    _str(h["command"], "holdout.command")
    if h["feedback"] not in ("names_and_messages", "counts_only"):
        raise ConfigError("holdout.feedback must be names_and_messages or counts_only")
    for role, val in cfg["roles"].items():
        if val not in ENGINE_NAMES and not (role == "review" and val == "cross"):
            raise ConfigError(f"roles.{role}: unknown engine {val!r}")
    if cfg["cross"] is not None:
        for builder, reviewer in _obj(cfg["cross"], "cross", ENGINE_NAMES).items():
            if reviewer not in ENGINE_NAMES or reviewer == builder:
                raise ConfigError(f"cross.{builder} must name a different valid engine")
    for en, ev in cfg["engines"].items():
        for k, val in ev.items():
            if k == "max_usd_per_run":
                _num(val, f"engines.{en}.{k}")
            elif k == "sandbox":
                if val not in ("workspace-write", "bypass"):
                    raise ConfigError("engines.codex.sandbox must be workspace-write or bypass")
            else:
                _str(val, f"engines.{en}.{k}")
    b = cfg["budgets"]
    for k in ("attempts", "engine_timeout_min", "run_timeout_min", "review_rounds"):
        _num(b[k], f"budgets.{k}", integer=True)
    _num(b["project_max_usd"], "budgets.project_max_usd")
    for x in _strlist(cfg["protected"], "protected"):
        safe_relpath(x, "protected")
    s = cfg["stack"]
    if s.get("type") not in ("compose", "host"):
        raise ConfigError("stack.type must be compose or host")
    safe_relpath(_str(s.get("file", "compose.yaml"), "stack.file"), "stack.file")
    if s["type"] == "host":
        if not isinstance(s.get("reason"), str) or not s["reason"].strip():
            raise ConfigError("stack.type 'host' requires a written stack.reason")
    if cfg["merge"] not in MERGE_POLICIES:
        raise ConfigError(f"merge must be one of {MERGE_POLICIES}")
    if cfg["notify"] not in ("hermes", "none"):
        raise ConfigError("notify must be hermes or none")
    return cfg


def config_path(root: Path | str) -> Path:
    return Path(root) / ".factory" / "config.json"


def plan_path(root: Path | str) -> Path:
    return Path(root) / ".factory" / "plan.json"


def _load(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"{what} not found: {path}") from None
    except json.JSONDecodeError as e:
        raise ConfigError(f"{what} is not valid JSON: {e}") from None


def load_config(root: Path | str) -> dict:
    return validate_config(_load(config_path(root), "config"))


MILESTONE_KEYS = {"id", "title", "goal", "acceptance", "allowed_paths", "builder", "reviewer",
                  "ui", "checkpoint", "verify_as"}


def validate_milestone(m: dict, where: str = "milestone") -> dict:
    _obj(m, where, MILESTONE_KEYS)
    for k in ("id", "title", "goal", "acceptance", "allowed_paths"):
        if k not in m:
            raise ConfigError(f"{where}: missing '{k}'")
    if not isinstance(m["id"], str) or not MILESTONE_RE.match(m["id"]) or m["id"] == "M0":
        raise ConfigError(f"{where}: id must look like M1, M2, ... (M0 is reserved)")
    _str(m["title"], f"{m['id']}.title")
    _str(m["goal"], f"{m['id']}.goal")
    _strlist(m["acceptance"], f"{m['id']}.acceptance", allow_empty=False)
    for p in _strlist(m["allowed_paths"], f"{m['id']}.allowed_paths", allow_empty=False):
        safe_relpath(p, f"{m['id']}.allowed_paths")
    if "builder" in m and m["builder"] not in ENGINE_NAMES:
        raise ConfigError(f"{m['id']}.builder: unknown engine {m['builder']!r}")
    if "reviewer" in m and m["reviewer"] not in ENGINE_NAMES and m["reviewer"] != "cross":
        raise ConfigError(f"{m['id']}.reviewer: unknown engine {m['reviewer']!r}")
    for k in ("ui", "checkpoint"):
        if k in m:
            _bool(m[k], f"{m['id']}.{k}")
    if "verify_as" in m and not (isinstance(m["verify_as"], str)
                                 and re.match(r"^M\d+$", m["verify_as"])):
        raise ConfigError(f"{m['id']}.verify_as must be a milestone id")
    return m


def validate_plan(raw: dict) -> dict:
    _obj(raw, "plan", {"milestones", "frozen", "holdout"})
    ms = raw.get("milestones")
    if not isinstance(ms, list) or not ms:
        raise ConfigError("plan.milestones must be a non-empty list")
    seen = set()
    for i, m in enumerate(ms):
        validate_milestone(m, f"milestones[{i}]")
        if m["id"] in seen:
            raise ConfigError(f"duplicate milestone id {m['id']}")
        seen.add(m["id"])
    out = {"milestones": ms, "frozen": [], "holdout": []}
    for k in ("frozen", "holdout"):
        if k in raw:
            out[k] = [safe_relpath(x, f"plan.{k}") for x in _strlist(raw[k], f"plan.{k}")]
    return out


def load_plan(root: Path | str) -> dict:
    return validate_plan(_load(plan_path(root), "plan"))


def milestone_def(root: Path | str, mid: str, extra: dict | None = None) -> dict:
    """Milestone definition: virtual M0, follow-ups kept in factory state, then plan.json."""
    if mid == "M0":
        return {"id": "M0", "title": "Contracts, skeleton, frozen tests and plan",
                "goal": "Write the contract: SPEC, tests, verify.sh, holdouts, plan.",
                "acceptance": ["scripts/verify.sh and .factory/plan.json exist and are valid"],
                "allowed_paths": ["**"]}
    if extra and mid in extra:
        return validate_milestone(dict(extra[mid]), f"extra {mid}")
    for m in load_plan(root)["milestones"]:
        if m["id"] == mid:
            return m
    raise ConfigError(f"milestone {mid} not found in plan or follow-ups")
