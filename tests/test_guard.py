import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import guard, hooks_adapters
from harness.types import GuardContext

CASES = json.loads((Path(__file__).resolve().parent.parent / "contract" / "guard-cases.json").read_text())
CTX = GuardContext(**CASES["context"])


class TestContractCases(unittest.TestCase):
    def test_all_cases(self):
        for case in CASES["cases"]:
            with self.subTest(case=case["id"]):
                d = guard.evaluate(case["tool"], case["input"], CTX)
                self.assertEqual(d.decision, case["expect"], f"{case['id']}: {d.reason}")


class TestNormalize(unittest.TestCase):
    def test_hermes_v4a_patch(self):
        text = ("*** Begin Patch\n*** Update File: a/b.py\n@@\n-x\n+y\n"
                "*** Add File: c.txt\n+hi\n*** Delete File: .env\n*** End Patch")
        calls = guard.normalize_tool_call("patch", {"mode": "patch", "patch": text})
        self.assertEqual(calls, [("write", "a/b.py"), ("write", "c.txt"), ("write", ".env")])
        self.assertEqual(guard.decide_tool_call("patch", {"patch": text}, CTX).decision, "deny")

    def test_hermes_simple(self):
        self.assertEqual(guard.normalize_tool_call("write_file", {"path": "x.py"}), [("write", "x.py")])
        self.assertEqual(guard.normalize_tool_call("terminal", {"command": "ls"}), [("shell", "ls")])
        self.assertEqual(guard.normalize_tool_call("read_file", {"path": ".env"}), [])

    def test_claude_multiedit(self):
        calls = guard.normalize_tool_call("MultiEdit", {"file_path": "tests/test_engine.py", "edits": []})
        self.assertEqual(calls, [("write", "tests/test_engine.py")])
        self.assertEqual(guard.decide_tool_call("MultiEdit", {"file_path": "tests/test_engine.py"}, CTX).decision, "deny")
        self.assertEqual(guard.normalize_tool_call("NotebookEdit", {"notebook_path": "n.ipynb"}), [("write", "n.ipynb")])
        self.assertEqual(guard.normalize_tool_call("Bash", {"command": "ls"}), [("shell", "ls")])

    def test_codex_shell_list(self):
        calls = guard.normalize_tool_call("shell", {"command": ["bash", "-lc", "rm -rf /"]})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "shell")
        self.assertEqual(guard.decide_tool_call("shell", {"command": ["bash", "-lc", "echo x > .env"]}, CTX).decision, "deny")

    def test_codex_apply_patch(self):
        d = guard.decide_tool_call("apply_patch", {"input": "*** Begin Patch\n*** Update File: .env\n*** End Patch"}, CTX)
        self.assertEqual(d.decision, "deny")

    def test_most_severe_wins(self):
        d = guard.decide_tool_call("Bash", {"command": "git reset --hard && git push"}, CTX)
        self.assertEqual(d.decision, "deny")


class TestFailClosed(unittest.TestCase):
    def test_internal_error(self):
        with mock.patch.object(guard, "_inspect", side_effect=RuntimeError("boom")):
            d = guard.check_shell("ls", CTX)
        self.assertEqual(d.decision, "deny")
        self.assertTrue(d.reason.startswith("guard error"))
        with mock.patch.object(guard, "normalize_tool_call", side_effect=RuntimeError("boom")):
            d = guard.decide_tool_call("Bash", {"command": "ls"}, CTX)
        self.assertEqual((d.decision, d.reason.startswith("guard error")), ("deny", True))


class TestAdapters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.env = {"HARNESS_ROOT": self.root}

    def tearDown(self):
        self.tmp.cleanup()

    def hermes(self, tool, inp, env=None):
        raw = json.dumps({"hook_event_name": "pre_tool_call", "tool_name": tool, "tool_input": inp,
                          "cwd": self.root})
        out, code = hooks_adapters.hermes_pre_tool_call(raw, env or self.env)
        return json.loads(out), code

    def claude(self, tool, inp, env=None):
        raw = json.dumps({"tool_name": tool, "tool_input": inp, "cwd": self.root})
        return hooks_adapters.claude_pre_tool_use(raw, env or self.env)

    def test_hermes_deny(self):
        out, code = self.hermes("terminal", {"command": "git push"})
        self.assertEqual((out["action"], code), ("block", 0))
        self.assertIn("push", out["message"])

    def test_hermes_ask_unattended_and_attended(self):
        out, _ = self.hermes("terminal", {"command": "git reset --hard"})
        self.assertEqual(out["action"], "block")
        self.assertTrue(out["message"].startswith("needs human approval"))
        out, code = self.hermes("terminal", {"command": "git reset --hard"},
                                {**self.env, "HARNESS_UNATTENDED": "0"})
        self.assertEqual((out["action"], code), ("approve", 0))

    def test_hermes_allow(self):
        self.assertEqual(self.hermes("write_file", {"path": "src/a.py"}), ({}, 0))

    def test_hermes_frozen_from_file(self):
        Path(self.root, ".harness").mkdir()
        Path(self.root, ".harness", "frozen.json").write_text('["tests/t.py"]')
        out, _ = self.hermes("write_file", {"path": "tests/t.py"})
        self.assertEqual(out["action"], "block")
        ff = Path(self.root, "alt.json")
        ff.write_text('["x.txt"]')
        out, _ = self.hermes("write_file", {"path": "x.txt"}, {**self.env, "HARNESS_FROZEN_FILE": str(ff)})
        self.assertEqual(out["action"], "block")

    def test_hermes_malformed(self):
        out, code = hooks_adapters.hermes_pre_tool_call("{not json", self.env)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["action"], "block")

    def test_claude_deny(self):
        out, code = self.claude("Bash", {"command": "echo x > .env"})
        self.assertEqual(code, 2)
        hso = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((hso["hookEventName"], hso["permissionDecision"]), ("PreToolUse", "deny"))

    def test_claude_ask(self):
        out, code = self.claude("Bash", {"command": "git clean -fdx"})
        self.assertEqual(code, 2)
        out, code = self.claude("Bash", {"command": "git clean -fdx"}, {**self.env, "HARNESS_UNATTENDED": "0"})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_claude_allow(self):
        self.assertEqual(self.claude("Edit", {"file_path": "src/a.py"}), ("", 0))
        self.assertEqual(self.claude("Read", {"file_path": ".env"}), ("", 0))

    def test_claude_malformed(self):
        out, code = hooks_adapters.claude_pre_tool_use("garbage", self.env)
        self.assertEqual(code, 2)
        self.assertIn("guard error", out)


if __name__ == "__main__":
    unittest.main()


class ContractPhaseTests(unittest.TestCase):
    """M0 must be able to write .harness/plan.json and tests/holdout/ (found in a live run)."""

    def test_m0_allows_plan_and_holdouts_but_not_config(self):
        from harness.types import GuardContext
        from harness import guard
        m0 = GuardContext(root="/repo", contract_phase=True)
        later = GuardContext(root="/repo")
        self.assertEqual(guard.check_write(".harness/plan.json", m0).decision, "allow")
        self.assertEqual(guard.check_write("tests/holdout/test_x.py", m0).decision, "allow")
        self.assertEqual(guard.check_shell("mkdir -p tests/holdout && echo x > tests/holdout/a.py", m0).decision, "allow")
        self.assertEqual(guard.check_write(".harness/config.json", m0).decision, "deny")
        self.assertEqual(guard.check_write(".harness/plan.json", later).decision, "deny")
        self.assertEqual(guard.check_write("tests/holdout/test_x.py", later).decision, "deny")

    def test_adapter_sets_contract_phase_from_milestone(self):
        import json
        from harness import hooks_adapters
        raw = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/repo/.harness/plan.json"}, "cwd": "/repo"})
        _, rc = hooks_adapters.claude_pre_tool_use(raw, {"HARNESS_ROOT": "/repo", "HARNESS_MILESTONE": "M0"})
        self.assertEqual(rc, 0)
        _, rc = hooks_adapters.claude_pre_tool_use(raw, {"HARNESS_ROOT": "/repo", "HARNESS_MILESTONE": "M1"})
        self.assertEqual(rc, 2)
