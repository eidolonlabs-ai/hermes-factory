"""Packaging: bundled data lookup, the Hermes plugin (guard fails closed), and `factory setup`."""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory import hermes_setup, resources  # noqa: E402


def load_plugin():
    spec = importlib.util.spec_from_file_location("factory_hermes_plugin", ROOT / "hermes" / "plugin" / "__init__.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_exe(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class ResourcesTests(unittest.TestCase):
    def test_data_dirs_resolve_in_a_checkout(self):
        self.assertTrue((resources.data_dir("template") / "AGENTS.md").is_file())
        self.assertTrue((resources.data_dir("template") / ".factory" / "config.json").is_file())
        self.assertTrue((resources.data_dir("plugin") / "plugin.yaml").is_file())
        self.assertTrue((resources.data_dir("plugin") / "skills" / "factory" / "SKILL.md").is_file())
        self.assertTrue((resources.data_dir("profiles") / "factory-coder" / "profile.json").is_file())
        with self.assertRaises(KeyError):
            resources.data_dir("nope")

    def test_versions_agree(self):
        from factory import __version__
        manifest = (ROOT / "hermes" / "plugin" / "plugin.yaml").read_text()
        self.assertIn(f"version: {__version__}\n", manifest)


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_plugin()
        self.tmp = Path(tempfile.mkdtemp(prefix="hh-plugin-")).resolve()
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        self.wt = self.tmp / "wt"
        (self.wt / "scripts").mkdir(parents=True)
        self.frozen = self.tmp / "frozen.json"
        self.frozen.write_text(json.dumps(["scripts/verify.sh"]))
        # The real adapter, run the way an installed `factory-hook` runs it.
        self.hook = write_exe(self.tmp / "factory-hook", "#!/bin/sh\n"
                              f'PYTHONPATH="{ROOT}" exec "{sys.executable}" -m factory.hooks_adapters "$@"\n')

    def env(self, **over):
        base = {k: v for k, v in os.environ.items()
                if not k.startswith("FACTORY_") and k != "HERMES_HOME"}
        base["FACTORY_HOME"] = str(self.tmp / "home")
        base.update(over)
        return mock.patch.dict(os.environ, base, clear=True)

    def run_env(self, **over):
        return self.env(**{"FACTORY_ROOT": str(self.wt), "FACTORY_FROZEN_FILE": str(self.frozen),
                           "FACTORY_HOOK_BIN": str(self.hook), **over})

    def test_register_declares_hooks_and_skills(self):
        hooks, skills = [], []
        ctx = mock.Mock()
        ctx.register_hook.side_effect = lambda name, fn: hooks.append(name)
        ctx.register_skill.side_effect = lambda name, path: skills.append((name, Path(path).is_file()))
        self.plugin.register(ctx)
        self.assertEqual(hooks, ["pre_tool_call", "pre_verify"])
        self.assertEqual(skills, [("factory", True), ("factory-worker", True)])

    def test_inactive_outside_factory_runs(self):
        with self.env(FACTORY_HOOK_BIN="/nonexistent/factory-hook"):
            self.assertIsNone(self.plugin.guard("terminal", {"command": "git push"}))

    def test_active_in_coder_profile_and_in_runs(self):
        self.assertTrue(self.plugin.guard_active({"HERMES_HOME": "/x/.hermes/profiles/factory-coder"}))
        self.assertTrue(self.plugin.guard_active({"FACTORY_ROOT": "/wt"}))
        self.assertFalse(self.plugin.guard_active({"HERMES_HOME": "/x/.hermes/profiles/other"}))
        self.assertFalse(self.plugin.guard_active({"HERMES_HOME": "/x/.hermes"}))

    def test_real_adapter_blocks_frozen_write_and_allows_other(self):
        with self.run_env():
            res = self.plugin.guard("terminal", {"command": "echo x > scripts/verify.sh"})
            self.assertEqual(res["action"], "block", res)
            self.assertIsNone(self.plugin.guard("terminal", {"command": "echo x > src/a.txt"}))

    def test_missing_engine_blocks(self):
        with self.run_env(FACTORY_HOOK_BIN="/nonexistent/factory-hook"):
            res = self.plugin.guard("terminal", {"command": "ls"})
        self.assertEqual(res["action"], "block")
        self.assertIn("factory-hook", res["message"])

    def test_broken_hook_blocks(self):
        cases = {"crash": "#!/bin/sh\nexit 3\n", "garbage": "#!/bin/sh\necho not-json\n",
                 "nonobject": "#!/bin/sh\necho '[1]'\n", "odd": "#!/bin/sh\necho '{\"action\": \"maybe\"}'\n"}
        for name, body in cases.items():
            exe = write_exe(self.tmp / name, body)
            with self.run_env(FACTORY_HOOK_BIN=str(exe)):
                res = self.plugin.guard("terminal", {"command": "ls"})
            self.assertEqual((res or {}).get("action"), "block", name)

    def test_hung_hook_blocks(self):
        exe = write_exe(self.tmp / "hang", "#!/bin/sh\nexec sleep 30\n")
        setattr(self.plugin, "_TIMEOUT_S", 1)
        with self.run_env(FACTORY_HOOK_BIN=str(exe)):
            res = self.plugin.guard("terminal", {"command": "ls"})
        self.assertEqual(res["action"], "block")

    def test_bad_arguments_block_instead_of_raising(self):
        with self.run_env():
            self.plugin.guard("terminal", {"command": object()})  # must not raise
            self.assertEqual(self.plugin.guard("terminal", "not-a-dict"), None)
        with self.run_env(), mock.patch.object(self.plugin, "_cwd", side_effect=RuntimeError("boom")):
            self.assertEqual(self.plugin.guard("terminal", {"command": "ls"})["action"], "block")

    def test_verify_nudge(self):
        with self.env(FACTORY_MILESTONE="M2"):
            self.assertIsNone(self.plugin.verify_nudge())  # not a factory session
        with self.run_env(FACTORY_MILESTONE="M2"):
            res = self.plugin.verify_nudge(coding=True, attempt=0)
            self.assertEqual(res["action"], "continue")
            self.assertIn("scripts/verify.sh M2", res["message"])
            self.assertIsNone(self.plugin.verify_nudge(coding=True, attempt=1))
            self.assertIsNone(self.plugin.verify_nudge(coding=False, attempt=0))
        with self.run_env(FACTORY_MILESTONE="M0"):
            self.assertIsNone(self.plugin.verify_nudge())
        with self.run_env():
            self.assertIsNone(self.plugin.verify_nudge())

    def test_profile_comes_from_hermes_inside_a_shared_gateway(self):
        """One gateway process serves every profile: HERMES_HOME is the root home there."""
        ctx = mock.Mock()
        self.plugin.register(ctx)
        ctx.profile_name = "factory-coder"
        with self.env(HERMES_HOME="/x/.hermes", FACTORY_HOOK_BIN="/nonexistent/factory-hook"):
            self.assertEqual(self.plugin.guard("terminal", {"command": "ls"})["action"], "block")
            ctx.profile_name = "default"
            self.assertIsNone(self.plugin.guard("terminal", {"command": "ls"}))

    def test_gateway_session_is_guarded_through_the_live_run_registry(self):
        """No FACTORY_* variables reach the gateway; the adapter finds the run by its registry."""
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.kill)
        active = self.tmp / "home" / "active"
        active.mkdir(parents=True)
        (active / "r1.json").write_text(json.dumps({
            "pid": sleeper.pid, "run_id": "r1", "root": str(self.wt), "frozen_file": str(self.frozen),
            "milestone": "M3"}))
        ctx = mock.Mock()
        self.plugin.register(ctx)
        ctx.profile_name = "factory-coder"
        with self.env(FACTORY_HOOK_BIN=str(self.hook)), \
                mock.patch.object(self.plugin, "_cwd", return_value=str(Path.home())):
            res = self.plugin.guard("terminal", {"command": "echo x > scripts/verify.sh"})
            self.assertEqual(res["action"], "block", res)
            self.assertIsNone(self.plugin.guard("terminal", {"command": "echo x > src/a.txt"}))
            self.assertIn("scripts/verify.sh M3", self.plugin.verify_nudge(coding=True, attempt=0)["message"])


LEGACY = """model: x

# >>> hermes-agent-factory hooks
# Guard every tool call (CONTRACT.md §8); fail closed if the guard itself breaks.
hooks:
  pre_tool_call:
    - matcher: ".*"
      command: "/old/bin/factory-hook hermes"
      fail_closed: true
# <<< hermes-agent-factory hooks
"""

FAKE_HERMES = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
if [ "$1" = "profile" ] && [ "$2" = "create" ]; then
  mkdir -p "$FAKE_ROOT/profiles/$3"
  printf '%s' "$FAKE_CONFIG" > "$FAKE_ROOT/profiles/$3/config.yaml"
  echo "cloned soul" > "$FAKE_ROOT/profiles/$3/SOUL.md"
fi
exit 0
"""


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hh-setup-")).resolve()
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        self.home = self.tmp / "hermes"
        self.home.mkdir()
        bindir = self.tmp / "bin"
        bindir.mkdir()
        write_exe(bindir / "hermes", FAKE_HERMES)
        write_exe(bindir / "factory-hook", "#!/bin/sh\necho '{}'\n")
        self.log = self.tmp / "hermes.log"
        patcher = mock.patch.dict(os.environ, {
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "HERMES_HOME": str(self.home),
            "FAKE_LOG": str(self.log), "FAKE_ROOT": str(self.home), "FAKE_CONFIG": LEGACY,
            "FACTORY_HOME": str(self.tmp / "factory-home")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_dry_run_changes_nothing(self):
        res = hermes_setup.run_setup(dry_run=True)
        self.assertTrue(res["ok"])
        self.assertTrue(all(a.startswith("would ") for a in res["actions"]), res["actions"])
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.calls(), [])

    def test_setup_installs_skills_profiles_and_plugin(self):
        res = hermes_setup.run_setup()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["warnings"], [])
        self.assertTrue((self.home / "skills/software-factory/factory/SKILL.md").is_file())
        self.assertTrue((self.home / "skills/software-factory/factory/references/benchmarking.md").is_file())
        coder, worker = self.home / "profiles/factory-coder", self.home / "profiles/factory-worker"
        self.assertTrue((coder / "plugins/factory/plugin.yaml").is_file())
        self.assertTrue((coder / "plugins/factory/skills/factory/SKILL.md").is_file())
        self.assertFalse((worker / "plugins/factory").exists())
        self.assertTrue((worker / "skills/software-factory/factory-worker/SKILL.md").is_file())
        cfg = (coder / "config.yaml").read_text()
        self.assertNotIn("hermes-agent-factory hooks", cfg)
        self.assertNotIn("factory-hook", cfg)
        self.assertIn("model: x", cfg)
        self.assertIn("hermes-agent-factory hooks", (worker / "config.yaml").read_text())  # not ours to edit
        for pdir in (coder, worker):  # role file from the definition; the cloned one is kept
            self.assertIn(hermes_setup.SOUL_MARK.format(name=pdir.name), (pdir / "SOUL.md").read_text())
            self.assertEqual((pdir / "SOUL.md.pre-factory").read_text(), "cloned soul\n")
        calls = self.calls()
        self.assertEqual(sum(c.startswith("profile create factory-coder --clone") for c in calls), 1)
        self.assertIn("-p factory-coder plugins enable factory --no-allow-tool-override", calls)
        self.assertFalse(any("factory-worker plugins enable" in c for c in calls))

    def test_setup_is_idempotent(self):
        hermes_setup.run_setup()
        (self.home / "profiles/factory-coder/plugins/factory/stale.txt").write_text("x")
        res = hermes_setup.run_setup()
        self.assertTrue(res["ok"])
        self.assertEqual(sum("profile create" in c for c in self.calls()), 2)  # one per profile, once
        self.assertFalse((self.home / "profiles/factory-coder/plugins/factory/stale.txt").exists())

    def test_profile_home_resolves_to_root_profiles_dir(self):
        active = self.home / "profiles" / "mine"
        active.mkdir(parents=True)
        self.assertEqual(hermes_setup.profiles_root(active), self.home / "profiles")
        self.assertEqual(hermes_setup.profiles_root(self.home), self.home / "profiles")

    def test_refuses_while_a_run_is_live(self):
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.kill)
        active = self.tmp / "factory-home" / "active"
        active.mkdir(parents=True)
        (active / "r9.json").write_text(json.dumps({"pid": sleeper.pid, "run_id": "r9"}))
        res = hermes_setup.run_setup()
        self.assertFalse(res["ok"])
        self.assertIn("r9", res["error"])
        self.assertEqual(self.calls(), [])
        self.assertTrue(hermes_setup.run_setup(dry_run=True)["ok"])

    def test_no_profiles_flag(self):
        res = hermes_setup.run_setup(with_profiles=False)
        self.assertTrue(res["ok"])
        self.assertFalse((self.home / "profiles").exists())
        self.assertEqual(self.calls(), [])

    def test_role_file_is_written_with_backup_when_a_definition_ships_one(self):
        src = self.tmp / "defs"
        (src / "p1").mkdir(parents=True)
        (src / "p1" / "profile.json").write_text('{"description": "d", "plugin": false}')
        (src / "p1" / "SOUL.md").write_text(hermes_setup.SOUL_MARK.format(name="p1") + "\nrole\n")
        real = hermes_setup.data_dir
        with mock.patch.object(hermes_setup, "data_dir", lambda n: src if n == "profiles" else real(n)):
            hermes_setup.run_setup()
        p1 = self.home / "profiles" / "p1"
        self.assertIn("role", (p1 / "SOUL.md").read_text())
        self.assertEqual((p1 / "SOUL.md.pre-factory").read_text(), "cloned soul\n")


if __name__ == "__main__":
    unittest.main()
