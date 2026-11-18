"""Diff/security audit: secrets, dangerous exec, XSS sinks, SQL interpolation, slice boundaries.

Port of agy-software-factory audit-diff.js. Patterns and the ignore marker are built
from joined segments so this file never flags itself.
"""
from __future__ import annotations

import os
import re
import subprocess

from .types import Check

SKIP_DIRS = {"node_modules", "dist", "build", "coverage", ".git", ".factory", ".factory"}
SKIP_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", ".DS_Store"}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tar", ".tgz",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".wasm", ".pyc", ".so", ".dylib",
    ".dll", ".exe",
}
PROSE_DOC_EXTENSIONS = {".md", ".markdown", ".txt"}
ENV_TEMPLATE_BASENAMES = {".env.example", ".env.sample", ".env.template", ".env.test"}
PLACEHOLDER_TOKENS = [
    "example", "changeme", "placeholder", "your_", "tasks_password", "dummy", "mock", "test",
    "sample", "replace", "xxxx", "0000", "todo",
]

IGNORE_MARKER = "-".join(["factory", "audit", "ignore"])


def _rx(parts: list[str], flags: int = 0) -> re.Pattern:
    return re.compile("".join(parts), flags)


AWS_KEY_RE = _rx([r"\bAKIA", r"[0-9A-Z]{16}\b"])
PEM_KEY_RE = _rx(["-----BEGIN ", "(?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?", "PRIVATE KEY-----"])
SECRET_ASSIGN_RE = _rx([r"\b(api[_-]?key|secret|token|password)", r"\s*[:=]\s*", r"""['"]([^'"]{8,})['"]"""], re.I)

EVAL_RE = _rx([r"\beval", r"\s*\("])
NEW_FUNCTION_RE = _rx([r"\bnew\s+Function", r"\s*\("])
SHELL_EXEC_INTERP_RE = _rx([r"\b(?:exec|execSync)", r"\s*\(\s*`[^`]*\$", r"\{"])
PY_EXEC_RE = _rx([r"(?<![\w.])(?<!def )exec", r"\s*\("])
PY_OS_SYSTEM_RE = _rx([r"\bos\.sys", r"tem\s*\("])
PY_SHELL_TRUE_RE = _rx([r"\bsubprocess\.\w+\(", r".*\bshell\s*=\s*Tr", "ue"])
PY_FSTRING_RE = _rx([r"""\b[fF][rR]?(['"])"""])

REACT_XSS_RE = _rx([r"\bdangerouslySet", r"InnerHTML\b"])
INNER_HTML_RE = _rx([r"\.innerHTML", r"\s*="])

SQL_SELECT_RE = _rx([r"\bSELECT\b.*\bWHERE\b.*(?<!\$)\$", r"\{"], re.I)
SQL_VALUES_RE = _rx([r"\bVALUES\s*\(.*(?<!\$)\$", r"\{"], re.I)
SQL_DELETE_RE = _rx([r"\bDELETE\s+FROM\b.*\bWHERE\b.*(?<!\$)\$", r"\{"], re.I)
SQL_UPDATE_RE = _rx([r"\bUPDATE\b.*\bSET\b.*(?:['\"]\s*\$", r"\{|\bWHERE\b.*(?<!\$)\$", r"\{)"], re.I)
PY_SQL_FSTRING_RE = _rx([r"""\b[fF]([rR]?)(['"])(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b.*\{.*\2"""], re.I)
PY_SQL_FORMAT_RE = _rx([r"""(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b.*['"]\s*\.for""", r"mat\s*\("], re.I)


# ---------------------------------------------------------------- glob helpers

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


# ---------------------------------------------------------------- file collection

def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)


def _git_top(cwd: str) -> str | None:
    try:
        r = _git(["rev-parse", "--show-toplevel"], cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    top = r.stdout.strip()
    if r.returncode != 0 or not top or not os.path.exists(top):
        return None
    return os.path.realpath(top)


def _should_skip(rel: str) -> bool:
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return True
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return True
    base = parts[-1]
    if base in SKIP_FILES:
        return True
    return os.path.splitext(base)[1].lower() in BINARY_EXTENSIONS


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def _walk(root: str) -> list[tuple[str, str]]:
    acc: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if not _should_skip(rel):
                acc.append((full, rel))
    return acc


def _git_changed(real_root: str, top: str, base: str | None) -> list[tuple[str, str]]:
    paths: set[str] = set()
    st = _git(["status", "--porcelain", "-z", "-uall"], real_root)
    if st.returncode == 0 and st.stdout:
        toks = st.stdout.split("\0")
        i = 0
        while i < len(toks):
            entry = toks[i]
            i += 1
            if not entry or len(entry) < 4:
                continue
            xy, rel = entry[:2], entry[3:]
            if xy[0] in "RC":
                i += 1
            if xy.strip() == "D":
                continue
            paths.add(os.path.normpath(os.path.join(top, rel)))
    if base is not None and base.strip():
        df = _git(["diff", "--name-only", "-z", base.strip(), "--"], real_root)
        if df.returncode == 0 and df.stdout:
            for rel in df.stdout.split("\0"):
                if rel:
                    paths.add(os.path.normpath(os.path.join(top, rel)))
    out = []
    for cand in paths:
        if not _inside(cand, real_root):
            continue
        if os.path.islink(cand) or not os.path.isfile(cand):
            continue
        if not _inside(os.path.realpath(cand), real_root):
            continue
        rel = os.path.relpath(cand, real_root).replace(os.sep, "/")
        if not _should_skip(rel):
            out.append((cand, rel))
    return out


# ---------------------------------------------------------------- scanning

def _is_placeholder(value: str) -> bool:
    low = value.lower()
    if "$" + "{" in low or "<" in low or ">" in low:
        return True
    return any(t in low for t in PLACEHOLDER_TOKENS)


def _finding(rule, severity, rel, line, snippet, message) -> dict:
    return {"rule": rule, "severity": severity, "file": rel, "line": line,
            "snippet": snippet, "message": message}


def _scan_file(abs_path: str, rel: str) -> tuple[bool, list[dict]]:
    try:
        with open(abs_path, "rb") as fh:
            buf = fh.read()
    except OSError:
        return False, []
    if b"\0" in buf[:8192]:
        return False, []
    lines = re.split(r"\r?\n", buf.decode("utf-8", errors="replace"))
    base = rel.rsplit("/", 1)[-1]
    ext = os.path.splitext(base)[1].lower()
    prose = ext in PROSE_DOC_EXTENSIONS
    env_template = base in ENV_TEMPLATE_BASENAMES
    findings: list[dict] = []

    for idx, raw in enumerate(lines):
        if not raw or IGNORE_MARKER in raw:
            continue
        n = idx + 1
        snip = raw.strip()[:200]

        if AWS_KEY_RE.search(raw):
            findings.append(_finding("hardcoded-secret", "high", rel, n, snip,
                                     "Potential hardcoded AWS Access Key ID detected."))
        elif PEM_KEY_RE.search(raw):
            findings.append(_finding("hardcoded-secret", "high", rel, n, snip,
                                     "Private key header detected in source file."))
        elif not prose and not env_template:
            m = SECRET_ASSIGN_RE.search(raw)
            if m and not _is_placeholder(m.group(2)):
                findings.append(_finding("hardcoded-secret", "high", rel, n, snip,
                                         f"Potential hardcoded {m.group(1)} assignment detected."))
        if prose:
            continue

        if (EVAL_RE.search(raw) or NEW_FUNCTION_RE.search(raw) or SHELL_EXEC_INTERP_RE.search(raw)
                or PY_EXEC_RE.search(raw) or PY_OS_SYSTEM_RE.search(raw)
                or (PY_SHELL_TRUE_RE.search(raw) and PY_FSTRING_RE.search(raw))):
            findings.append(_finding(
                "dangerous-exec", "high", rel, n, snip,
                "Dynamic code or shell command interpolation via ev" "al(), ex" "ec(), Function(), "
                "os.sys" "tem(), shell=Tr" "ue f-string, or child_process exec template literal detected."))

        if REACT_XSS_RE.search(raw) or INNER_HTML_RE.search(raw):
            findings.append(_finding("xss-sink", "medium", rel, n, snip,
                                     "Unescaped HTML sink (dangerouslySet" "InnerHTML / innerHTML) detected."))

        if (SQL_SELECT_RE.search(raw) or SQL_VALUES_RE.search(raw) or SQL_DELETE_RE.search(raw)
                or SQL_UPDATE_RE.search(raw) or PY_SQL_FSTRING_RE.search(raw)
                or PY_SQL_FORMAT_RE.search(raw)):
            findings.append(_finding(
                "sql-interpolation", "high", rel, n, snip,
                "Raw string/template interpolation inside SQL statement; use parameterized queries."))
    return True, findings


def audit(root: str, base: str | None = None, all_files: bool = False,
          allow_paths: list[str] | None = None) -> dict:
    if base is not None and str(base).strip().startswith("-"):
        raise ValueError(f'Invalid base revision "{str(base).strip()}": revision must not start with "-".')
    resolved = os.path.abspath(root)
    real = os.path.realpath(resolved)
    allowed = normalize_allow_paths(allow_paths)
    top = None if all_files else _git_top(real)
    cands = _git_changed(real, top, base) if top else _walk(real)
    cands.sort(key=lambda c: c[1])

    scanned = 0
    findings: list[dict] = []
    for abs_path, rel in cands:
        if allowed and not matches_allowed_path(rel, allowed):
            joined = ", ".join(allowed)
            findings.append(_finding(
                "slice-boundary-violation", "high", rel, 1, f"Allowed slice paths: {joined}",
                f'File "{rel}" is outside allowed slice ownership ({joined}).'))
        ok, fs = _scan_file(abs_path, rel)
        if ok:
            scanned += 1
            findings.extend(fs)

    if any(f["severity"] == "high" for f in findings):
        status = "FLAGGED"
    elif findings:
        status = "WARN"
    else:
        status = "APPROVE_CANDIDATE"
    return {"root": resolved, "status": status, "files_scanned": scanned, "findings": findings}


# ---------------------------------------------------------------- formatters

def to_check(result: dict) -> Check:
    f = result["findings"]
    details = [f"{x['file']}:{x['line']} [{x['severity']}] {x['rule']}: {x['message']}" for x in f]
    n = result["files_scanned"]
    if result["status"] == "FLAGGED":
        high = sum(1 for x in f if x["severity"] == "high")
        return Check("audit-diff", "FAIL", f"{high} high-severity finding(s) in {n} file(s)", details)
    if result["status"] == "WARN":
        return Check("audit-diff", "PASS", f"{len(f)} non-blocking finding(s) in {n} file(s)", details)
    return Check("audit-diff", "PASS", f"no findings in {n} file(s)", details)


_SARIF_RULES = {
    "hardcoded-secret": ("HardcodedSecret", "Hardcoded secret, credential, or private key material"),
    "dangerous-exec": ("DangerousExec", "Dynamic code execution or unparameterized shell command interpolation"),
    "xss-sink": ("XssSink", "Unescaped HTML DOM sink"),
    "sql-interpolation": ("SqlInterpolation", "Unparameterized string interpolation inside SQL statement"),
    "slice-boundary-violation": ("SliceBoundaryViolation",
                                 "Modified file is outside assigned slice ownership boundaries"),
}


def to_sarif(result: dict) -> dict:
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "factory", "version": "1.0.0",
                "rules": [{"id": k, "name": v[0], "shortDescription": {"text": v[1]}}
                          for k, v in _SARIF_RULES.items()],
            }},
            "results": [{
                "ruleId": f["rule"],
                "level": "error" if f["severity"] == "high" else "warning",
                "message": {"text": f["message"]},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": f["file"]},
                    "region": {"startLine": f["line"] if isinstance(f["line"], int) and f["line"] > 0 else 1},
                }}],
            } for f in result["findings"]],
        }],
    }


def to_markdown(result: dict) -> str:
    lines = [
        f"## Diff & Security Audit: {result['status']}",
        "",
        f"- **Workspace**: `{result.get('root', '')}`",
        f"- **Files Scanned**: **{result['files_scanned']}**",
        f"- **Findings**: **{len(result['findings'])}**",
    ]
    if result["findings"]:
        lines += ["", "| Severity | Rule | Location | Message |", "| :--- | :--- | :--- | :--- |"]
        for f in result["findings"]:
            msg = str(f.get("message", "")).replace("|", "\\|")
            lines.append(f"| **{f['severity'].upper()}** | `{f['rule']}` | `{f['file']}:{f['line']}` | {msg} |")
    return "\n".join(lines)
