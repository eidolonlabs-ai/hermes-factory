"""Shared helpers for tests/test_core_*.py: temp git repos, fake engines, HARNESS_HOME."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import holdout, state  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}

VERIFY_SH = """#!/bin/sh
# trivial verify: milestone passes when src/feature.txt exists
test -f src/feature.txt
"""
HOLDOUT_SH = """#!/bin/sh
test -f tests/holdout/h.txt || { echo "holdout not present"; exit 9; }
if [ "$(cat src/feature.txt 2>/dev/null)" = "ok" ]; then exit 0; fi
echo "SECRET_SOURCE: assert feature() == 'ok'  # holdout source line"
echo "FAILED tests/holdout/h.py::test_feature - AssertionError: expected ok"
echo "1 failed, 2 passed"
exit 1
"""

CONFIG = {"project": "demo",
          "verify": {"command": "scripts/verify.sh {milestone}", "timeout_min": 1, "require_tests": True},
          "holdout": {"enabled": True, "command": "scripts/holdout.sh {milestone}",
                      "feedback": "names_and_messages"},
          "roles": {"architect": "fake", "backend": "fake", "ui": "fake", "review": "fake"},
          "budgets": {"attempts": 2, "engine_timeout_min": 1, "run_timeout_min": 5,
                      "review_rounds": 1, "project_max_usd": 10},
          "protected": ["scripts/verify.sh", ".harness/"],
          "stack": {"type": "host", "reason": "unit tests"}, "merge": "ff", "notify": "none"}

PLAN = {"milestones": [
    {"id": "M1", "title": "one", "goal": "feature one", "acceptance": ["feature exists"],
     "allowed_paths": ["src/"]},
    {"id": "M2", "title": "two", "goal": "feature two", "acceptance": ["still exists"],
     "allowed_paths": ["src/"], "checkpoint": True},
    {"id": "M3", "title": "three", "goal": "feature three", "acceptance": ["still exists"],
     "allowed_paths": ["src/"]}],
    "frozen": ["spec/frozen.txt", "scripts/verify.sh", "scripts/holdout.sh"], "holdout": []}


def git(repo, *args):
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=env).stdout.strip()


class CoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._old = {k: os.environ.get(k) for k in ("HARNESS_HOME", "HARNESS_FAKE_ENGINE", *GIT_ENV)}
        os.environ["HARNESS_HOME"] = str(self.tmp / "home")
        os.environ.update(GIT_ENV)
        self.addCleanup(self._restore)
        self.repo = self.tmp / "repo"

    def _restore(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def make_repo(self, config=None, plan=None, holdout=False, freeze=True, verify=VERIFY_SH):
        r = self.repo
        for f, body in {"scripts/verify.sh": verify, "scripts/holdout.sh": HOLDOUT_SH,
                        "spec/frozen.txt": "frozen\n", "src/.gitkeep": "", "README.md": "x\n",
                        ".harness/config.json": json.dumps(config or CONFIG),
                        ".harness/plan.json": json.dumps(plan or PLAN)}.items():
            p = r / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        os.chmod(r / "scripts/verify.sh", 0o755)
        os.chmod(r / "scripts/holdout.sh", 0o755)
        if holdout:
            (r / "tests/holdout").mkdir(parents=True)
            (r / "tests/holdout/h.txt").write_text("SECRET_SOURCE hidden test body\n")
        subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "init")
        state.init_project("demo", str(r))
        if freeze:
            holdout_mod = holdout_module()
            holdout_mod.freeze(r, "demo")
        return r

    def fake(self, body: str) -> Path:
        """Write a fake engine script. It runs with cwd=worktree; env has HARNESS_ATTEMPT/ROLE."""
        p = self.tmp / f"fake_{len(list(self.tmp.glob('fake_*.py')))}.py"
        p.write_text("import os, sys, pathlib\nA = int(os.environ['HARNESS_ATTEMPT'])\n"
                     "ROLE = os.environ['HARNESS_ROLE']\n" + textwrap.dedent(body))
        os.environ["HARNESS_FAKE_ENGINE"] = str(p)
        return p

    def run_ms(self, milestone="M1", role="build", **kw):
        from harness import runner
        return runner.execute_run("demo", milestone, role, "fake", **kw)


def holdout_module():
    return holdout
