"""Docker Compose policy + isolated per-run stack sessions (DESIGN.md §8, CONTRACT.md §4).

Stdlib only. All docker output goes to log files, never stdout.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from .types import Check

DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")


def project_name(project: str, run_id: str) -> str:
    """'<project>-<8 hex of sha1(run_id)>' matching [a-z0-9][a-z0-9_-]*.

    Hashing the whole run id keeps names unique: run ids share date prefixes, so a plain
    truncation would make two runs on the same day share one compose project.
    """
    import hashlib
    p = re.sub(r"[^a-z0-9_-]+", "-", (project or "").lower()).strip("-_")[:40]
    r = hashlib.sha1((run_id or "").encode()).hexdigest()[:8] if run_id else ""
    name = "-".join(x for x in (p, r) if x) or "factory"
    return name if re.match(r"[a-z0-9]", name[0]) else "h" + name


def _env(env: dict | None, name: str | None = None, run_id: str | None = None) -> dict:
    e = dict(os.environ)
    e.update(env or {})
    if name:
        e["COMPOSE_PROJECT_NAME"] = name
    if run_id is not None:
        e["FACTORY_RUN_ID"] = run_id
    else:
        e.setdefault("FACTORY_RUN_ID", "")
    return e


def docker_available() -> tuple[bool, str]:
    try:
        r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return False, "docker daemon not reachable: " + (r.stderr.strip()[:200])
        c = subprocess.run(["docker", "compose", "version", "--short"],
                           capture_output=True, text=True, timeout=20)
        if c.returncode != 0:
            return False, "docker compose v2 not available"
        ver = c.stdout.strip().lstrip("v")
        if not ver.startswith(("2", "3", "4", "5", "6", "7", "8", "9")):
            return False, f"docker compose v2+ required, found {ver}"
        return True, f"docker {r.stdout.strip()}, compose {ver}"
    except FileNotFoundError:
        return False, "docker binary not found"
    except subprocess.TimeoutExpired:
        return False, "docker timed out"


def load_config(worktree: str, compose_file: str, project_name: str, env: dict | None = None,
                timeout_s: float = 60) -> dict:
    """`docker compose config --format json`. Raises RuntimeError on failure."""
    argv = ["docker", "compose", "-f", str(compose_file), "-p", project_name,
            "config", "--format", "json"]
    try:
        r = subprocess.run(argv, cwd=worktree, env=_env(env, project_name), capture_output=True,
                           text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"docker compose config timed out after {timeout_s}s") from e
    if r.returncode != 0:
        raise RuntimeError("docker compose config failed: " + r.stderr.strip()[:500])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"docker compose config returned invalid JSON: {e}") from e


def _is_docker_path(p: str) -> bool:
    home = os.path.expanduser("~")
    n = os.path.normpath(p)
    if n in DOCKER_SOCKETS or n.endswith("docker.sock"):
        return True
    for d in (os.path.join(home, ".docker"), "/root/.docker"):
        if n == d or n.startswith(d + os.sep):
            return True
    return False


def _inside(path: str, root: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def policy_violations(cfg: dict, worktree: str, protected_projects: list[str],
                      allow_published_ports: bool = False) -> list[str]:
    """Pure policy check on a `compose config --format json` dict."""
    v: list[str] = []
    name = cfg.get("name")
    if name and name in (protected_projects or []):
        v.append(f"project name '{name}' is protected")
    for sname, svc in (cfg.get("services") or {}).items():
        svc = svc or {}
        if svc.get("container_name"):
            v.append(f"{sname}: container_name is not allowed ({svc['container_name']})")
        if svc.get("privileged"):
            v.append(f"{sname}: privileged is not allowed")
        if svc.get("network_mode") == "host":
            v.append(f"{sname}: network_mode host is not allowed")
        if svc.get("pid") == "host":
            v.append(f"{sname}: pid host is not allowed")
        if svc.get("ipc") == "host":
            v.append(f"{sname}: ipc host is not allowed")
        for cap in svc.get("cap_add") or []:
            if str(cap).upper().removeprefix("CAP_") in ("ALL", "SYS_ADMIN"):
                v.append(f"{sname}: cap_add {cap} is not allowed")
        if svc.get("devices"):
            v.append(f"{sname}: devices are not allowed")
        if not allow_published_ports and svc.get("ports"):
            v.append(f"{sname}: published ports are not allowed during gates")
        for vol in svc.get("volumes") or []:
            if isinstance(vol, str):
                src, vtype = vol.split(":")[0], ("bind" if vol.startswith(("/", ".", "~")) else "volume")
            else:
                src, vtype = vol.get("source") or "", vol.get("type", "")
            if not src:
                continue
            if _is_docker_path(src):
                v.append(f"{sname}: docker socket/config mount is not allowed ({src})")
            elif vtype == "bind" and not _inside(src, worktree):
                v.append(f"{sname}: bind mount outside worktree is not allowed ({src})")
    for nname, net in (cfg.get("networks") or {}).items():
        if net and net.get("external"):
            v.append(f"network {nname}: external networks are not allowed")
    for vname, vol in (cfg.get("volumes") or {}).items():
        if vol and vol.get("external"):
            v.append(f"volume {vname}: external volumes are not allowed")
    return v


def policy_check(worktree: str, compose_file: str, project: str, protected_projects: list[str],
                 env: dict | None = None, allow_published_ports: bool = False) -> Check:
    """`project` is the full compose project name."""
    t0 = time.time()
    try:
        cfg = load_config(worktree, compose_file, project, env)
    except RuntimeError as e:
        return Check("compose-policy", "FAIL", "could not load compose config", [str(e)],
                     duration_s=time.time() - t0)
    cfg.setdefault("name", project)
    viol = policy_violations(cfg, worktree, protected_projects, allow_published_ports)
    if viol:
        return Check("compose-policy", "FAIL", f"{len(viol)} compose policy violation(s)", viol,
                     duration_s=time.time() - t0)
    return Check("compose-policy", "PASS", "compose policy ok", duration_s=time.time() - t0)


def snapshot_foreign(project_name: str, timeout_s: float = 30) -> set[str]:
    """'<id>:<state>' for all containers NOT in the given compose project."""
    r = subprocess.run(["docker", "ps", "-a", "--no-trunc", "--format", "json"],
                       capture_output=True, text=True, timeout=timeout_s)
    if r.returncode != 0:
        raise RuntimeError("docker ps failed: " + r.stderr.strip()[:300])
    out: set[str] = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        labels = c.get("Labels") or ""
        if isinstance(labels, str):
            labels = dict(kv.split("=", 1) for kv in labels.split(",") if "=" in kv)
        if labels.get("com.docker.compose.project") == project_name:
            continue
        # id:state:name:project — id and state decide; name/project make reports traceable
        out.add(f"{c.get('ID', '')}:{c.get('State', '')}:{c.get('Names', '')}:"
                f"{labels.get('com.docker.compose.project', '-')}")
    return out


class ComposeSession:
    def __init__(self, worktree: str, compose_file: str, project_name: str, env: dict | None,
                 artifacts_dir: str, timeout_s: float = 300, run_id: str | None = None):
        self.worktree = str(worktree)
        self.compose_file = str(compose_file)
        self.project_name = project_name
        self.artifacts_dir = Path(artifacts_dir)
        self.timeout_s = timeout_s
        self.env = _env(env, project_name, run_id if run_id is not None else (env or {}).get("FACTORY_RUN_ID", project_name))
        self.foreign_changed: list[str] = []
        self.teardown_ok: bool = False
        self._before: set[str] | None = None
        self._n = 0

    def _base(self) -> list[str]:
        return ["docker", "compose", "-f", self.compose_file, "-p", self.project_name]

    def _run(self, label: str, argv: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
        """Run argv; stdout+stderr appended to artifacts_dir/compose-<label>.log."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._n += 1
        log = self.artifacts_dir / f"compose-{self._n:02d}-{label}.log"
        t = timeout or self.timeout_s
        with open(log, "wb") as fh:
            fh.write(("$ " + " ".join(argv) + "\n").encode())
            fh.flush()
            try:
                r = subprocess.run(argv, cwd=self.worktree, env=self.env, stdin=subprocess.DEVNULL,
                                   stdout=fh, stderr=subprocess.STDOUT, timeout=t)
            except subprocess.TimeoutExpired:
                fh.write(f"\n[factory] timed out after {t}s\n".encode())
                r = subprocess.CompletedProcess(argv, 124)
        r.log = str(log)  # type: ignore[attr-defined]
        return r

    def __enter__(self) -> "ComposeSession":
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._before = snapshot_foreign(self.project_name)
        return self

    def up(self, wait: bool = True, build: bool = True) -> subprocess.CompletedProcess:
        argv = self._base() + ["up", "-d"]
        if build:
            argv.append("--build")
        if wait:
            argv += ["--wait", "--wait-timeout", str(int(self.timeout_s))]
        return self._run("up", argv, self.timeout_s + 30)

    def run(self, service: str, argv: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
        return self._run(f"run-{service}", self._base() + ["run", "--rm", "-T", service] + list(argv), timeout)

    def exec(self, service: str, argv: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
        return self._run(f"exec-{service}", self._base() + ["exec", "-T", service] + list(argv), timeout)

    def logs_to(self, artifacts_dir: str | None = None) -> str:
        d = Path(artifacts_dir) if artifacts_dir else self.artifacts_dir
        d.mkdir(parents=True, exist_ok=True)
        path = d / "compose-logs.log"
        with open(path, "wb") as fh:
            try:
                subprocess.run(self._base() + ["logs", "--no-color", "--timestamps"], cwd=self.worktree,
                               env=self.env, stdin=subprocess.DEVNULL, stdout=fh,
                               stderr=subprocess.STDOUT, timeout=60)
            except (subprocess.TimeoutExpired, OSError) as e:
                fh.write(f"\n[factory] logs failed: {e}\n".encode())
        return str(path)

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self.logs_to()
        except Exception:
            pass
        ok = False
        try:
            r = self._run("down", self._base() + ["down", "-v", "--remove-orphans", "--rmi", "local"], 120)
            ok = r.returncode == 0
        except Exception:
            ok = False
        try:
            after = snapshot_foreign(self.project_name)
            self.foreign_changed = sorted((self._before or set()) ^ after)
        except Exception as e:
            self.foreign_changed = [f"snapshot failed: {e}"]
            ok = False
        self.teardown_ok = ok
        return False


def published_ports(name: str, cwd: str, timeout_s: float = 30) -> dict[str, list[str]]:
    """{service: ["http://localhost:PORT (-> container port)", ...]} for one compose project."""
    r = subprocess.run(["docker", "compose", "-p", name, "ps", "--format", "json"], cwd=cwd,
                       capture_output=True, text=True, timeout=timeout_s)
    out: dict[str, list[str]] = {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items = json.loads(line)
        except json.JSONDecodeError:
            continue
        for c in items if isinstance(items, list) else [items]:
            for p in c.get("Publishers") or []:
                if p.get("PublishedPort"):
                    out.setdefault(c.get("Service", "?"), []).append(
                        f"http://localhost:{p['PublishedPort']} (-> {p.get('TargetPort')}/{p.get('Protocol', 'tcp')})")
    return {k: sorted(set(v)) for k, v in out.items()}


def preview(repo: str, compose_file: str, project: str, overlay: str = "compose.preview.yaml",
            down: bool = False, log: str | Path | None = None, timeout_s: float = 600) -> dict:
    """Boot (or tear down) the merged app with published ports for humans / browser checks.

    Uses its own project `<project>-preview` so it never collides with gate or engine stacks.
    The base file must still pass the policy (no container_name, socket, privileged, ...);
    published ports are allowed here only because this is not a gate.
    """
    name = project_name(project, "") + "-preview"
    files = ["-f", compose_file] + (["-f", overlay] if (Path(repo) / overlay).exists() else [])
    log = Path(log or Path(repo) / ".factory-preview.log")
    if down:
        rc = down_project(name, repo, log)
        return {"project": name, "down": rc == 0}
    cfg = load_config(repo, compose_file, name)
    cfg.setdefault("name", name)
    viol = policy_violations(cfg, repo, [], allow_published_ports=True)
    if viol:
        return {"project": name, "ok": False, "violations": viol}
    with open(log, "ab") as fh:
        try:
            r = subprocess.run(["docker", "compose", "-p", name, *files, "up", "-d", "--build", "--wait",
                                "--wait-timeout", str(int(timeout_s))], cwd=repo, stdin=subprocess.DEVNULL,
                               stdout=fh, stderr=subprocess.STDOUT, timeout=timeout_s + 60)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    return {"project": name, "ok": rc == 0, "log": str(log), "urls": published_ports(name, repo),
            "stop": "factory preview --down"}


def down_project(name: str, cwd: str, log: str | Path, timeout_s: float = 180) -> int:
    """`docker compose -p NAME down -v --remove-orphans` for one named project only.

    Compose v2 finds the project's resources by label, so no compose file is needed.
    Returns the exit code (124 on timeout). Output goes to `log`.
    """
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as fh:
        try:
            r = subprocess.run(["docker", "compose", "-p", name, "down", "-v", "--remove-orphans"],
                               cwd=cwd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=timeout_s)
            return r.returncode
        except subprocess.TimeoutExpired:
            return 124


def teardown_check(session: ComposeSession) -> Check:
    """Fail if our teardown failed or a foreign container disappeared during the run.

    Foreign containers that merely changed state (e.g. another project restarted) are
    reported but do not fail the gate: the user may legitimately be working on them.
    """
    before = set(session._before or set())
    after = before ^ set(session.foreign_changed)       # foreign_changed is the symmetric diff
    ids = lambda entries: {e.split(":", 1)[0] for e in entries}
    removed = sorted(e for e in before if e.split(":", 1)[0] in ids(before) - ids(after))
    other = sorted(e for e in session.foreign_changed if e not in removed)
    if not session.teardown_ok:
        return Check("compose-teardown", "FAIL", "docker compose down failed or snapshot unavailable",
                     list(session.foreign_changed), log=str(session.artifacts_dir))
    if removed:
        return Check("compose-teardown", "FAIL", "containers outside this project were removed",
                     [f"removed {r}" for r in removed] + other, log=str(session.artifacts_dir))
    if other:
        return Check("compose-teardown", "PASS", "stack torn down; foreign containers changed state (not by us?)",
                     other, log=str(session.artifacts_dir))
    return Check("compose-teardown", "PASS", "stack torn down; no foreign containers changed")
