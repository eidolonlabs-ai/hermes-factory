"""Pre-tool guard policy (CONTRACT.md section 8). Stdlib only.

Ported from the agy-software-factory Node guard. The guard is a convenience that blocks
honest mistakes early; the gate stays the authority. It never raises: any internal error
becomes a deny (fail closed).

Public API:
    check_write(path, ctx)   -> Decision   file write/edit tool
    check_shell(command, ctx)-> Decision   shell command run from the repo root
    evaluate(tool, payload, ctx)           tool in {"write", "shell"}
    normalize_tool_call(name, input)       real agent tool call -> [(kind, value)]
    decide_tool_call(name, input, ctx)     most severe decision over a tool call
"""
from __future__ import annotations

import os
import posixpath
import re
import shlex

from factory.types import Decision, GuardContext

ALLOW = Decision("allow")

# --------------------------------------------------------------------------- file rules

ENV_TEMPLATES = {".env.example", ".env.sample", ".env.template", ".env.test"}
PRIVATE_KEY_BASENAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}
SEVERITY = {"allow": 0, "ask": 1, "deny": 2}


def _worst(decisions) -> Decision:
    """Most severe decision (deny > ask > allow); first of equal severity wins."""
    worst = ALLOW
    for d in decisions:
        if SEVERITY[d.decision] > SEVERITY[worst.decision]:
            worst = d
    return worst


def _relativize_all(path: str, root: str, cwd: str = "") -> list[str]:
    """Normalise to repo-relative POSIX path(s) across lexical and symlink-resolved forms.
    Empty list means 'outside the repo'."""
    p = path.strip().replace("\\", "/")
    if not p:
        return []
    if p.startswith("~"):
        return []  # home dir: not the guard's concern (rm of ~ itself is handled in shell)
    if p in ("$PWD", "${PWD}"):
        p = "."
    elif p.startswith("$PWD/"):
        p = "./" + p[5:]
    elif p.startswith("${PWD}/"):
        p = "./" + p[7:]

    if p.startswith("/"):
        p = re.sub(r"^/+", "/", p)
        cand_norm = posixpath.normpath(p)
        cand_real = os.path.realpath(p).replace("\\", "/")
    else:
        base = (cwd or root or "").strip().replace("\\", "/")
        if base:
            joined = base.rstrip("/") + "/" + p
            cand_norm = posixpath.normpath(joined)
            cand_real = os.path.realpath(joined).replace("\\", "/")
        else:
            n = posixpath.normpath(p)
            if n.startswith("../") or n == "..":
                return []
            return [n]

    if not root:
        return [cand_norm]

    root_norm = posixpath.normpath(root.strip().replace("\\", "/")).rstrip("/")
    root_real = os.path.realpath(root).replace("\\", "/").rstrip("/")

    def _strip(cand: str, r: str) -> str | None:
        if r and (cand == r or cand.startswith(r + "/")):
            return cand[len(r):].lstrip("/") or "."
        return None

    out: list[str] = []
    # Check symlink-resolved path first (deterministic; prevents set hash-order bypasses),
    # then lexical path (catches symlinks inside the repo pointing outside).
    for cand, r in (
        (cand_real, root_real),
        (cand_real, root_norm),
        (cand_norm, root_norm),
        (cand_norm, root_real),
    ):
        rel = _strip(cand, r)
        if rel is not None and rel not in out:
            out.append(rel)
    return out


def _relativize(path: str, root: str, cwd: str = "") -> str | None:
    """Normalise to a repo-relative POSIX path. None means 'outside the repo'."""
    rels = _relativize_all(path, root, cwd)
    return rels[0] if rels else None


def _check_rel(rel: str, ctx: GuardContext, is_dir: bool = False) -> Decision:
    """Policy for a repo-relative normalised path. is_dir: the target may be a directory
    (rm/mv/cp -t), so also catch deleting a parent of protected files."""
    low = rel.lower()
    as_dir = rel + "/"
    as_dir_low = low + "/"
    parts = low.split("/")
    base = parts[-1]

    if is_dir and low in (".", "*"):
        return Decision("deny", f"Blocked destructive repo-root operation on: {rel}")

    # .git internals (config, HEAD, hooks, refs, ...) - and the .git dir itself when removed
    if ".git" in parts[:-1] or base == ".git":
        return Decision("deny", f"Blocked modification of .git internals: {rel}")

    # factory control directory (receipts, plans, run state)
    cd = ctx.control_dir.strip("/").lower()
    # M0 (contract phase) exists to write the plan and the holdouts; config stays protected.
    if ctx.contract_phase and not is_dir and low == f"{cd}/plan.json":
        return ALLOW
    if cd and (low == cd or low.startswith(cd + "/") or f"/{cd}/" in f"/{low}/"):
        return Decision("deny", f"Blocked direct modification of factory control state: {rel}")

    # holdout tests: marker anywhere in the path ("holdout/" must be at a component start)
    for m in ([] if ctx.contract_phase else ctx.holdout_markers):
        ml = m.lower()
        hay = "/" + (as_dir_low if is_dir else low)
        needle = ml
        if ml.endswith("/"):
            if "/" + needle in hay:
                return Decision("deny", f"Blocked modification of holdout tests: {rel}")
        elif needle in hay:
            return Decision("deny", f"Blocked modification of holdout tests: {rel}")

    # frozen files (frozen at checkpoint 1); deleting a parent dir also counts
    for f in ctx.frozen:
        raw = f.replace("\\", "/")
        fn = posixpath.normpath(raw)
        fn_low = fn.lower()
        if low == fn_low or (is_dir and fn_low.startswith(as_dir_low)):
            return Decision("deny", f"Blocked modification of frozen file: {fn}")
        # Frozen directory ("tests/"): existing files inside are frozen; NEW files may be added.
        if raw.endswith("/") and low.startswith(fn_low + "/"):
            if is_dir or os.path.lexists(os.path.join(ctx.root, rel)):
                return Decision("deny", f"Blocked modification of frozen file under {fn}/: {rel}")

    # secrets
    if (base == ".env" or base.startswith(".env.")) and base not in ENV_TEMPLATES:
        return Decision("deny", f"Blocked write to secret environment file: {base}")
    if base in PRIVATE_KEY_BASENAMES or base.endswith(".pem") or base.endswith(".key"):
        return Decision("deny", f"Blocked write to private key file: {base}")
    return ALLOW


def _check_write(path: str, ctx: GuardContext, is_dir: bool = False) -> Decision:
    rels = _relativize_all(path, ctx.root, ctx.cwd)
    if not rels:
        return ALLOW
    return _worst(_check_rel(rel, ctx, is_dir) for rel in rels)


def check_write(path: str, ctx: GuardContext) -> Decision:
    """Decision for a file write/edit tool call."""
    try:
        return _check_write(path, ctx)
    except Exception as exc:  # fail closed
        return Decision("deny", f"guard error: {exc}")


# --------------------------------------------------------------------------- shell parsing

_AMP_REDIR = re.compile(r"[<>]")


def _read_sub(s: str, i: int) -> tuple[str, int]:
    """s[i] is just after '$('. Return (inner text, index after the matching ')')."""
    depth, j, quote = 1, i, None
    n = len(s)
    while j < n and depth > 0:
        ch = s[j]
        if quote == "'":
            if ch == "'":
                quote = None
            j += 1
        elif ch == "\\" and j + 1 < n:
            j += 2
        elif ch == "$" and j + 1 < n and s[j + 1] == "(":
            _, j = _read_sub(s, j + 2)
        elif quote == '"':
            if ch == '"':
                quote = None
            j += 1
        elif ch in ("'", '"'):
            quote = ch
            j += 1
        elif ch == "(":
            depth += 1
            j += 1
        elif ch == ")":
            depth -= 1
            j += 1
        else:
            j += 1
    return s[i:j - 1] if depth == 0 else s[i:j], j


def _read_backtick(s: str, i: int) -> tuple[str, int]:
    j, n = i, len(s)
    while j < n:
        if s[j] == "\\" and j + 1 < n:
            j += 2
            continue
        if s[j] == "`":
            return s[i:j], j + 1
        j += 1
    return s[i:j], j


def split_segments(cmd: str) -> list[str]:
    """Split on ; && || | & newline and subshell parens; recurse into $(...) and backticks
    (also inside double quotes). Single quotes are literal."""
    segs: list[str] = []
    cur = ""
    quote = None
    i = 0
    n = len(cmd)

    def flush():
        nonlocal cur
        if cur.strip():
            segs.append(cur.strip())
        cur = ""

    while i < n:
        ch = cmd[i]
        prev = cmd[i - 1] if i else ""
        nxt = cmd[i + 1] if i + 1 < n else ""
        if quote == "'":
            cur += ch
            if ch == "'":
                quote = None
        elif ch == "\\" and i + 1 < n:
            cur += ch + nxt
            i += 2
            continue
        elif ch == "$" and nxt == "(":
            sub, i = _read_sub(cmd, i + 2)
            segs.extend(split_segments(sub))
            continue
        elif ch == "`":
            sub, i = _read_backtick(cmd, i + 1)
            segs.extend(split_segments(sub))
            continue
        elif quote == '"':
            cur += ch
            if ch == '"':
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch in ";\n()":
            flush()
        elif ch in "&|":
            if nxt == ch:  # && or ||
                flush()
                i += 1
            elif ch == "&" and (nxt == ">" or prev in "<>"):  # &>file, 2>&1: redirect syntax
                cur += ch
            else:  # single | or &
                flush()
        else:
            cur += ch
        i += 1
    flush()
    return segs


def tokenize(segment: str) -> list[str]:
    """Whitespace/redirect tokens with quotes and backslash escapes resolved."""
    tokens: list[str] = []
    cur: list[str] = []
    in_token = False
    quote: str | None = None
    i = 0
    n = len(segment)

    def flush():
        nonlocal cur, in_token
        if in_token or cur:
            tokens.append("".join(cur))
        cur = []
        in_token = False

    while i < n:
        ch = segment[i]
        if quote == "'":
            if ch == "'":
                quote = None
            else:
                cur.append(ch)
            in_token = True
            i += 1
        elif quote == '"':
            if ch == '"':
                quote = None
            elif ch == "\\" and i + 1 < n and segment[i + 1] in ('"', "\\", "$", "`", "\n"):
                cur.append(segment[i + 1])
                i += 2
                in_token = True
                continue
            else:
                cur.append(ch)
            in_token = True
            i += 1
        elif ch in ("'", '"'):
            quote = ch
            in_token = True
            i += 1
        elif ch == "\\" and i + 1 < n:
            cur.append(segment[i + 1])
            in_token = True
            i += 2
        elif ch.isspace():
            flush()
            i += 1
        elif ch in "<>":
            prefix = "".join(cur)
            if not (in_token and (prefix.isdigit() or prefix == "&")):
                flush()
            op = ch
            if i + 1 < n and (
                (ch == ">" and segment[i + 1] in (">", "|", "&"))
                or (ch == "<" and segment[i + 1] in ("<", ">", "&"))
            ):
                op += segment[i + 1]
                i += 2
                if op == ">&" and i < n and segment[i].isdigit():
                    op += segment[i]
                    i += 1
            else:
                i += 1
            cur.append(op)
            in_token = True
            flush()
        else:
            cur.append(ch)
            in_token = True
            i += 1
    flush()
    return tokens


_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SUDO_VALUED = {"-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-D", "-R", "-T"}
_ENV_VALUED = {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"}
_XARGS_VALUED = {"-I", "-i", "-L", "-l", "-n", "-P", "-s", "-d", "-E", "-J", "-a", "-R"}


def _strip_prefixes_ex(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Drop sudo/env/command/exec/nohup/time/xargs/control prefixes; return (tokens, extra_cmds)."""
    extra: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        base = posixpath.basename(t)
        if _ASSIGN.match(t) or t in ("{", "!", "}"):
            i += 1
        elif base in ("sudo", "env", "command", "exec", "nohup", "time", "builtin", "xargs"):
            i += 1
            if base == "sudo":
                while i < n and tokens[i].startswith("-"):
                    flag = tokens[i]
                    i += 1
                    if flag in _SUDO_VALUED and i < n:
                        i += 1
            elif base == "env":
                while i < n and (tokens[i].startswith("-") or _ASSIGN.match(tokens[i])):
                    flag = tokens[i]
                    i += 1
                    if flag in ("-S", "--split-string") and i < n:
                        extra.append(tokens[i])
                        i += 1
                    elif flag.startswith("--split-string="):
                        extra.append(flag.split("=", 1)[1])
                    elif flag.startswith("-S") and len(flag) > 2:
                        extra.append(flag[2:])
                    elif flag in _ENV_VALUED and i < n:
                        i += 1
            elif base == "exec":
                while i < n and tokens[i].startswith("-"):
                    flag = tokens[i]
                    i += 1
                    if flag == "-a" and i < n:
                        i += 1
            elif base == "xargs":
                while i < n and tokens[i].startswith("-"):
                    flag = tokens[i]
                    i += 1
                    if flag in _XARGS_VALUED and i < n:
                        i += 1
            else:
                while i < n and tokens[i].startswith("-"):
                    i += 1
        else:
            break
    out = tokens[i:]
    while out and out[-1] == "}":
        out = out[:-1]
    return out, extra


def strip_prefixes(tokens: list[str]) -> list[str]:
    """Drop sudo (+flags) / env / command / VAR=x prefixes."""
    return _strip_prefixes_ex(tokens)[0]


# --------------------------------------------------------------------------- shell rules

HOME_FORMS = ("~", "$HOME", "${HOME}")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_SHELL_VALUED = {"-o", "+o", "-O", "+O"}
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}

FORK_BOMB = re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
MKFS = re.compile(r"\bmkfs(\.[A-Za-z0-9_-]+)?\b")
# curl/wget ... | [sudo] sh|bash|zsh  (pipe-to-shell install)
PIPE_TO_SHELL = re.compile(r"\b(curl|wget)\b[^;&\n]*\|\s*(sudo\s+(-\S+\s+)*)?(env\s+\S+\s+)?"
                           r"(/\S*/)?(sh|bash|zsh|dash|ksh)\b")
# docker rm -f $(docker ps -aq) / `docker ps -aq` / ... | xargs docker rm
DOCKER_MASS = re.compile(r"\bdocker\s+(container\s+)?(rm|rmi|kill|stop)\b[^;\n]*(\$\(|`)\s*docker\s+"
                         r"(container\s+)?(ps|ls|images|image\s+ls)\b"
                         r"|\bdocker\s+(container\s+)?(ps|ls|images)\b[^;\n]*-\w*q[^;\n]*\|\s*xargs\s+docker\s+"
                         r"(container\s+)?(rm|rmi|kill|stop)\b")


def _norm_rm_target(raw: str) -> str:
    """Normalise an rm target for the catastrophic check ('//' and '/.' are '/')."""
    t = raw.strip()
    for home in HOME_FORMS:
        if t == home or t.startswith(home + "/"):
            suffix = t[len(home):]
            if not suffix:
                return home
            if re.fullmatch(r"/+\*", suffix):
                return home + "/*"
            norm = posixpath.normpath(re.sub(r"^/+", "/", suffix))
            return home + "/" if norm in ("/", "/.") else home + norm.rstrip("/")
    if re.fullmatch(r"/+\*", t):
        return "/*"
    if t.startswith("/"):
        return posixpath.normpath(re.sub(r"^/+", "/", t)).rstrip("/") or "/"
    return t


CATASTROPHIC = {"/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*",
                "${HOME}", "${HOME}/", "${HOME}/*"}


def _positional(args: list[str], value_flags: tuple[str, ...] = ()) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in value_flags:
            skip = True
        elif a == "--" or (a.startswith("-") and len(a) > 1):
            continue
        else:
            out.append(a)
    return out


def _target_dir_dests(args: list[str], is_ln: bool = False) -> tuple[list[str], list[str]]:
    """For cp/mv/ln/install: (destinations, sources). Handles -t / -ft / --target-directory."""
    dests, pos, has_t = [], [], False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos.extend(args[i + 1:])
            break
        if a == "--target-directory" or (a.startswith("-") and not a.startswith("--") and a.endswith("t")):
            has_t = True
            if i + 1 < len(args):
                dests.append(args[i + 1])
                i += 1
        elif a.startswith("--target-directory="):
            has_t = True
            dests.append(a.split("=", 1)[1])
        elif a.startswith("-t") and len(a) > 2:
            has_t = True
            dests.append(a[2:])
        elif a.startswith("-") and len(a) > 1:
            pass
        else:
            pos.append(a)
        i += 1
    if has_t:
        return dests, pos
    if len(pos) > 1:
        return [pos[-1]], pos[:-1]
    if is_ln and len(pos) == 1:
        return [posixpath.basename(pos[0].rstrip("/")) or pos[0]], []
    return pos, []


def _inplace_targets(cmd: str, args: list[str]) -> list[str]:
    """sed -i / perl -i: file operands (first positional is the script unless -e/-f given)."""
    in_place = False
    explicit = False
    pos: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos.extend(args[i + 1:])
            break
        if a == "--in-place" or a.startswith("--in-place="):
            in_place = True
        elif a.startswith("--expression=") or a.startswith("--file="):
            explicit = True
        elif a in ("--expression", "--file"):
            explicit = True
            i += 1
        elif a.startswith("-") and not a.startswith("--") and len(a) > 1:
            m = (re.match(r"^-([^-ef]*?)([ef])(.*)$", a) if cmd == "sed"
                 else re.match(r"^-([^-eE]*?)([eE])(.*)$", a))
            if m:
                if "i" in m.group(1):
                    in_place = True
                explicit = True
                if not m.group(3):
                    i += 1  # separate script operand follows
            elif "i" in a:
                in_place = True
        elif a.startswith("--"):
            pass
        else:
            pos.append(a)
        i += 1
    if not in_place:
        return []
    return pos if explicit or len(pos) <= 1 else pos[1:]


def _redirect_targets(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Split tokens into (non-redirect tokens, redirect targets) for > >> 1> 2> &> >| <>."""
    rest, targets = [], []
    i = 0
    pat = re.compile(r"^(?:\d*|&)(?:>>?\|?|<>)(.*)$")
    while i < len(tokens):
        t = tokens[i]
        m = pat.match(t)
        if m and not (t.startswith("<") and not t.startswith("<>")):
            tgt = m.group(1)
            if not tgt and i + 1 < len(tokens):
                tgt = tokens[i + 1]
                i += 1
            if tgt and not tgt.startswith("&"):  # 2>&1 duplicates an fd, writes nothing
                targets.append(tgt)
        else:
            rest.append(t)
        i += 1
    return rest, targets


def _git_decisions(args: list[str], ctx: GuardContext) -> list[Decision]:
    out: list[Decision] = []
    i = 0
    while i < len(args) and args[i].startswith("-"):  # skip global options
        i += 2 if args[i] in GIT_OPTS_WITH_VALUE else 1
    if i >= len(args):
        return out
    sub, rest = args[i], args[i + 1:]
    if sub == "push":
        out.append(Decision("deny", "Blocked git push: publishing is a human decision."))
    elif sub == "commit":
        _commit_val = {"-m", "-F", "-C", "-c", "-t", "--message", "--file", "--reuse-message",
                       "--reedit-message", "--template", "--author", "--date", "--fixup", "--squash"}
        j = 0
        while j < len(rest):
            a = rest[j]
            if a == "--":
                break
            if a in _commit_val or (a.startswith("-") and not a.startswith("--") and a[-1] in ("m", "F", "C", "c", "t")):
                if a.startswith("-") and not a.startswith("--") and "n" in a:
                    out.append(Decision("deny", "Blocked --no-verify/-n: hooks must not be bypassed."))
                j += 2
                continue
            if a == "--no-verify" or (a.startswith("-") and not a.startswith("--") and "n" in a):
                out.append(Decision("deny", "Blocked --no-verify/-n: hooks must not be bypassed."))
            j += 1
    elif sub == "config":
        pos = [a for a in rest if not a.startswith("-")]
        if any(a.lower() == "core.hookspath" or a.lower().startswith("core.hookspath=") for a in pos):
            if len(pos) >= 2 or any("=" in a for a in pos):
                out.append(Decision("deny", "Blocked modifying git config core.hooksPath."))
    elif sub == "reset" and "--hard" in rest:
        out.append(Decision("ask", "git reset --hard discards work: needs human approval."))
    elif sub == "clean" and any(
            a == "--force" or (a.startswith("-") and not a.startswith("--") and "f" in a) for a in rest):
        out.append(Decision("ask", "git clean -f deletes untracked files: needs human approval."))
    elif sub == "rebase" and any(a in ("-i", "--interactive") for a in rest):
        out.append(Decision("ask", "Interactive rebase rewrites history: needs human approval."))
    elif sub in ("checkout", "restore"):
        # paths after `--` or positionals on checkout/restore are checked against protected/frozen rules
        if "--" in rest:
            paths = rest[rest.index("--") + 1:]
        elif sub == "restore":
            paths = _positional(rest, ("-s", "--source"))
        else:
            paths = _positional(rest, ("-b", "-B", "--orphan", "--conflict", "--recurse-submodules", "-U", "--unified"))
        for p in paths:
            out.append(_check_write(p, ctx, True))
    return out


def _segment_decisions(tokens: list[str], ctx: GuardContext, depth: int) -> list[Decision]:
    out: list[Decision] = []
    tokens, extra1 = _strip_prefixes_ex(tokens)
    tokens, redirects = _redirect_targets(tokens)
    tokens, extra2 = _strip_prefixes_ex(tokens)
    for cmd_str in extra1 + extra2:
        out.append(_inspect(cmd_str, ctx, depth + 1))
    for r in redirects:  # redirect target is a write
        out.append(_check_write(r, ctx))
    if not tokens:
        return out
    cmd = posixpath.basename(tokens[0])
    args = tokens[1:]

    if "--no-verify" in tokens:  # skips git hooks
        out.append(Decision("deny", "Blocked --no-verify: hooks must not be bypassed."))

    if cmd in SHELLS:  # sh -c "..." : unwrap and inspect recursively
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--":
                break
            if a in _SHELL_VALUED:
                i += 2
                continue
            if a.startswith("-") and not a.startswith("--") and "c" in a:
                j = i + 1
                if j < len(args) and args[j] == "--":
                    j += 1
                if j < len(args):
                    out.append(_inspect(args[j], ctx, depth + 1))
                break
            i += 1
    elif cmd == "eval" and args:
        out.append(_inspect(" ".join(args), ctx, depth + 1))
    elif cmd == "rm":
        for t in _positional(args):
            if _norm_rm_target(t) in CATASTROPHIC:
                out.append(Decision("deny", f"Blocked catastrophic rm target: {t}"))
            out.append(_check_write(t, ctx, True))
    elif cmd in ("cp", "mv", "ln", "install"):
        dests, srcs = _target_dir_dests(args, is_ln=(cmd == "ln"))
        for d in dests:
            out.append(_check_write(d, ctx, True))
        if cmd == "mv":  # moving a source away is a deletion
            for s in srcs:
                out.append(_check_write(s, ctx, True))
    elif cmd in ("touch", "tee"):
        for t in _positional(args):
            out.append(_check_write(t, ctx))
    elif cmd == "truncate":
        for t in _positional(args, ("-s", "-r", "--size", "--reference")):
            out.append(_check_write(t, ctx))
    elif cmd in ("sed", "perl"):
        for t in _inplace_targets(cmd, args):
            out.append(_check_write(t, ctx))
    elif cmd == "dd":
        for a in args:
            if a.startswith("of="):
                out.append(_check_write(a[3:], ctx))
    elif cmd == "git":
        out.extend(_git_decisions(args, ctx))
    elif cmd == "docker":
        words = [a for a in args if not a.startswith("-")]
        if "prune" in words and words[0] in ("system", "volume", "image", "container", "network", "builder"):
            out.append(Decision("deny", "Blocked host-wide docker prune."))
    elif cmd == "mkfs" or cmd.startswith("mkfs."):
        out.append(Decision("deny", "Blocked filesystem formatting command (mkfs)."))
    return out


def _inspect(command: str, ctx: GuardContext, depth: int = 0) -> Decision:
    if not command or depth > 5:
        return ALLOW
    if FORK_BOMB.search(command):
        return Decision("deny", "Blocked shell fork bomb.")
    if MKFS.search(command):
        return Decision("deny", "Blocked filesystem formatting command (mkfs).")
    if PIPE_TO_SHELL.search(command):
        return Decision("deny", "Blocked pipe-to-shell install (curl/wget | sh).")
    if DOCKER_MASS.search(command):
        return Decision("deny", "Blocked mass docker rm of every container on the host.")
    decisions: list[Decision] = []
    for seg in split_segments(command):
        decisions.extend(_segment_decisions(tokenize(seg), ctx, depth))
    return _worst(decisions)


def check_shell(command: str, ctx: GuardContext) -> Decision:
    """Decision for a shell command run from the repo root. Reading is always allowed."""
    try:
        return _inspect(command, ctx)
    except Exception as exc:  # fail closed
        return Decision("deny", f"guard error: {exc}")


def evaluate(tool: str, payload, ctx: GuardContext) -> Decision:
    """tool in {'write','shell'}; payload is the path/command string or a dict holding it."""
    try:
        if isinstance(payload, dict):
            payload = payload.get("path") or payload.get("command") or payload.get("input") or ""
        if tool == "write":
            return check_write(payload, ctx)
        if tool == "shell":
            return check_shell(payload, ctx)
        return Decision("deny", f"guard error: unknown tool kind {tool!r}")
    except Exception as exc:
        return Decision("deny", f"guard error: {exc}")


# --------------------------------------------------------------------------- tool mapping

SHELL_TOOLS = {"terminal", "bash", "shell", "local_shell", "exec_command"}
WRITE_TOOLS = {"write_file", "write", "edit", "multiedit", "notebookedit", "patch", "apply_patch",
               "str_replace_editor"}
_PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+?)\s*$"
                         r"|^\*\*\* Move to:\s*(.+?)\s*$", re.M)
_DIFF_FILE = re.compile(r"^(?:\+\+\+|---)\s+(.+?)(?:\t.*)?$", re.M)


def _patch_paths(text: str) -> list[str]:
    paths = [a or b for a, b in _PATCH_FILE.findall(text)]
    for raw in _DIFF_FILE.findall(text):
        p = raw.strip()
        if p.startswith('"') and p.endswith('"') and len(p) >= 2:
            p = p[1:-1]
        if p.startswith(("a/", "b/")):
            p = p[2:]
        if p and p != "/dev/null":
            paths.append(p)
    return paths


def normalize_tool_call(tool_name: str, tool_input) -> list[tuple[str, str]]:
    """Map a real agent tool call to [(kind, value)] with kind in {'write','shell'}.
    Tools that only read (read_file, Read, Grep, ...) map to []."""
    name = (tool_name or "").lower()
    inp = tool_input if isinstance(tool_input, dict) else {}
    calls: list[tuple[str, str]] = []

    if name in SHELL_TOOLS or (name not in WRITE_TOOLS and ("command" in inp or "cmd" in inp)):
        cmd = inp.get("command", inp.get("cmd"))
        if isinstance(cmd, list):  # Codex: ["bash", "-lc", "..."]
            cmd = shlex.join(str(c) for c in cmd)
        if isinstance(cmd, str) and cmd.strip():
            calls.append(("shell", cmd))
        return calls

    if name in WRITE_TOOLS:
        for key in ("file_path", "notebook_path", "path"):
            if isinstance(inp.get(key), str) and inp[key]:
                calls.append(("write", inp[key]))
        # V4A / diff patch text: Hermes `patch`, Codex `apply_patch`
        for key in ("patch", "patch_text", "input", "diff"):
            if isinstance(inp.get(key), str):
                calls.extend(("write", p) for p in _patch_paths(inp[key]))
        if isinstance(tool_input, str):  # Codex apply_patch may pass the raw patch text
            calls.extend(("write", p) for p in _patch_paths(tool_input))
        for e in inp.get("edits", []) or []:  # MultiEdit edits share file_path; tolerate per-edit paths
            if isinstance(e, dict) and isinstance(e.get("file_path"), str):
                calls.append(("write", e["file_path"]))
    return list(dict.fromkeys(calls))


def decide_tool_call(tool_name: str, tool_input, ctx: GuardContext) -> Decision:
    """Most severe decision over every write/shell action implied by a tool call."""
    try:
        calls = normalize_tool_call(tool_name, tool_input)
        return _worst(evaluate(kind, value, ctx) for kind, value in calls)
    except Exception as exc:  # fail closed
        return Decision("deny", f"guard error: {exc}")
