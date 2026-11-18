"""Hook adapter integration details found in live checks against real Hermes / Claude runs."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory import guard, hooks_adapters  # noqa: E402
from factory.types import GuardContext  # noqa: E402


class HermesHookEnvTests(unittest.TestCase):
    """Hermes runs shell hooks from the profile home with a scrubbed env: no FACTORY_* vars,
    cwd = ~/.hermes. The adapter must still find the active run(s)."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="hh-home-")).resolve()
        self.old = os.environ.get("FACTORY_HOME")
        os.environ["FACTORY_HOME"] = str(self.home)
        self.wt = self.home / "worktrees" / "p" / "r1"
        (self.wt / "scripts").mkdir(parents=True)
        run = self.home / "runs" / "p" / "r1"
        run.mkdir(parents=True)
        (run / "frozen.json").write_text(json.dumps(["scripts/verify.sh"]))
        self.frozen_file = run / "frozen.json"

    def tearDown(self):
        if self.old is None:
            os.environ.pop("FACTORY_HOME", None)
        else:
            os.environ["FACTORY_HOME"] = self.old
        subprocess.run(["rm", "-rf", str(self.home)])

    def payload(self, cwd, cmd="echo x > scripts/verify.sh"):
        return json.dumps({"hook_event_name": "pre_tool_call", "tool_name": "terminal",
                           "tool_input": {"command": cmd}, "cwd": cwd})

    def test_no_env_no_active_run_allows(self):
        out, _ = hooks_adapters.hermes_pre_tool_call(self.payload("/somewhere"), {})
        self.assertEqual(json.loads(out), {})

    def test_active_run_registry_blocks_frozen_write(self):
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.kill)
        (self.home / "active").mkdir()
        (self.home / "active" / "r1.json").write_text(json.dumps(
            {"pid": sleeper.pid, "run_id": "r1", "root": str(self.wt), "frozen_file": str(self.frozen_file)}))
        out, _ = hooks_adapters.hermes_pre_tool_call(self.payload(str(Path.home())), {})
        self.assertEqual(json.loads(out)["action"], "block")
        out, _ = hooks_adapters.hermes_pre_tool_call(self.payload(str(Path.home()), "echo x > src/a.txt"), {})
        self.assertEqual(json.loads(out), {})

    def test_dead_runner_entry_is_ignored(self):
        p = subprocess.Popen(["true"]); p.wait()
        (self.home / "active").mkdir()
        (self.home / "active" / "r1.json").write_text(json.dumps(
            {"pid": p.pid, "run_id": "r1", "root": str(self.wt), "frozen_file": str(self.frozen_file)}))
        out, _ = hooks_adapters.hermes_pre_tool_call(self.payload(str(Path.home())), {})
        self.assertEqual(json.loads(out), {})

    def test_cwd_inside_worktree_finds_frozen_list(self):
        out, _ = hooks_adapters.hermes_pre_tool_call(self.payload(str(self.wt)), {})
        self.assertEqual(json.loads(out)["action"], "block")

    def test_worktree_subdir_resolves_root_without_frozen_file(self):
        (self.wt / "sub").mkdir()
        self.frozen_file.unlink()
        (self.frozen_file.parent).rmdir()
        p = json.dumps({"hook_event_name": "pre_tool_call", "tool_name": "write_file",
                        "tool_input": {"path": "../.factory/config.json"}, "cwd": str(self.wt / "sub")})
        out, _ = hooks_adapters.hermes_pre_tool_call(p, {})
        self.assertEqual(json.loads(out)["action"], "block")


class SymlinkPathTests(unittest.TestCase):
    def test_root_and_path_differ_only_by_symlink(self):
        real = Path(tempfile.mkdtemp()).resolve()
        link = Path(tempfile.mkdtemp()) / "link"
        os.symlink(real, link)
        ctx = GuardContext(root=str(link), frozen=["scripts/verify.sh"])
        d = guard.check_write(str(real / "scripts" / "verify.sh"), ctx)
        self.assertEqual(d.decision, "deny", d.reason)
        ctx2 = GuardContext(root=str(real), frozen=["scripts/verify.sh"])
        self.assertEqual(guard.check_write(str(link / "scripts" / "verify.sh"), ctx2).decision, "deny")


if __name__ == "__main__":
    unittest.main()
