import copy
import json
import os
import subprocess
import sys
import unittest
import zipfile

from core_support import CONFIG, PLAN, ROOT, CoreCase, git
from factory import engines, holdout, models, state
from factory.models import ConfigError

GOOD = """pathlib.Path('src').mkdir(exist_ok=True); pathlib.Path('src/feature.txt').write_text('ok')"""


class ModelTests(unittest.TestCase):
    def cfg(self, **kw):
        c = copy.deepcopy(CONFIG)
        c.update(kw)
        return c

    def test_valid_config_gets_defaults(self):
        c = models.validate_config({"project": "x"})
        self.assertEqual(c["stack"]["type"], "compose")
        self.assertEqual(c["budgets"]["attempts"], 3)

    def test_config_errors(self):
        bad = [{}, {"project": "bad name!"}, {"project": "x", "bogus": 1},
               {"project": "x", "stack": {"type": "host"}},
               {"project": "x", "stack": {"type": "vm"}},
               {"project": "x", "merge": "yolo"},
               {"project": "x", "verify": {"require_tests": "yes"}},
               {"project": "x", "budgets": {"attempts": 0}},
               {"project": "x", "budgets": {"nope": 1}},
               {"project": "x", "roles": {"ui": "cross"}},
               {"project": "x", "roles": {"architect": "gpt"}},
               {"project": "x", "protected": ["../etc"]},
               {"project": "x", "engines": {"claude": {"temperature": 1}}},
               {"project": "x", "verify": "scripts/verify.sh"}]
        for raw in bad:
            with self.assertRaises(ConfigError, msg=str(raw)):
                models.validate_config(raw)

    def test_plan_errors(self):
        good = copy.deepcopy(PLAN)
        models.validate_plan(good)
        def mut(f):
            p = copy.deepcopy(PLAN); f(p); return p
        bad = [mut(lambda p: p["milestones"].clear()),
               mut(lambda p: p["milestones"][0].pop("goal")),
               mut(lambda p: p["milestones"][0].update(id="M0")),
               mut(lambda p: p["milestones"][0].update(id="X1")),
               mut(lambda p: p["milestones"][1].update(id="M1")),
               mut(lambda p: p["milestones"][0].update(allowed_paths=[])),
               mut(lambda p: p["milestones"][0].update(builder="gpt")),
               mut(lambda p: p["milestones"][0].update(ui="yes")),
               mut(lambda p: p["milestones"][0].update(extra=1)),
               mut(lambda p: p.update(frozen=["/abs"])),
               mut(lambda p: p.update(surprise=[]))]
        for raw in bad:
            with self.assertRaises(ConfigError, msg=str(raw)):
                models.validate_plan(raw)


class HoldoutScrubTests(unittest.TestCase):
    def test_pytest_format(self):
        raw = ("def test_x():\n>   assert secret(1) == 2   # SOURCE\nE   assert 3 == 2\n"
               "FAILED tests/holdout/t.py::test_x - AssertionError: assert 3 == 2\n"
               "FAILED tests/holdout/t.py::test_y\n== 2 failed, 5 passed in 0.1s ==\n")
        s, d = holdout.scrub_output(raw)
        self.assertEqual(s, "holdouts: 2 failed, 5 passed")
        self.assertEqual(d, ["tests/holdout/t.py::test_x: AssertionError: assert 3 == 2",
                             "tests/holdout/t.py::test_y"])
        self.assertNotIn("SOURCE", json.dumps(d))

    def test_playwright_format(self):
        raw = ("  1) [chromium] › holdout/a.spec.ts:3:1 › cart › totals ────────\n\n"
               "    Error: expect(received).toBe(expected)\n\n    > 5 |   await page.click('#secret')\n"
               "  1 failed\n  4 passed (3s)\n")
        s, d = holdout.scrub_output(raw)
        self.assertEqual(s, "holdouts: 1 failed, 4 passed")
        self.assertEqual(len(d), 1)
        self.assertIn("holdout/a.spec.ts:3:1", d[0])
        self.assertIn("Error: expect(received).toBe(expected)", d[0])
        self.assertNotIn("page.click", d[0])

    def test_counts_only_and_unparseable(self):
        s, d = holdout.scrub_output("FAILED a::b - msg\n1 failed", "counts_only")
        self.assertEqual((s, d), ("holdouts: 1 failed", []))
        s, d = holdout.scrub_output("garbage with SECRET\n")
        self.assertEqual(d, [])
        self.assertNotIn("SECRET", s)


class EngineTests(CoreCase):
    def test_claude_argv_has_headless_fix_and_hook_settings(self):
        d = self.tmp / "run"; d.mkdir()
        cfg = models.validate_config({"project": "x"})
        inv = engines.build_invocation("claude", role="build", worktree=self.tmp, prompt="P",
                                       prompt_file=d / "p.md", run_dir=d, cfg=cfg, frozen=["a"])
        a = inv.argv
        self.assertIn("--strict-mcp-config", a)
        self.assertEqual(a[a.index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertEqual(inv.env["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
        self.assertEqual(inv.env["FACTORY_ROOT"], str(self.tmp))
        self.assertTrue(os.path.isfile(inv.env["FACTORY_FROZEN_FILE"]))
        # the in-engine guard must be able to read the frozen file (else it fails closed)
        from factory import hooks_adapters
        self.assertIsInstance(hooks_adapters._frozen(str(self.tmp), inv.env), list)
        settings = json.loads(__import__("pathlib").Path(a[a.index("--settings") + 1]).read_text())
        self.assertEqual(settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
                         f"{sys.executable} -m factory.hooks_adapters claude")
        self.assertEqual(inv.stdin_text, "P")

    def test_claude_hook_end_to_end_with_invocation_env(self):
        """The exact hook command from the per-run settings blocks frozen writes, allows others."""
        import subprocess as sp
        d = self.tmp / "run2"; d.mkdir()
        cfg = models.validate_config({"project": "x"})
        inv = engines.build_invocation("claude", role="build", worktree=self.tmp, prompt="P",
                                       prompt_file=d / "p.md", run_dir=d, cfg=cfg,
                                       frozen=["tests/test_a.py"])
        a = inv.argv
        cmd = json.loads(__import__("pathlib").Path(a[a.index("--settings") + 1]).read_text())[
            "hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        def call(tool, inp):
            return sp.run(cmd, shell=True, input=json.dumps({"tool_name": tool, "tool_input": inp,
                                                              "cwd": str(self.tmp)}),
                          capture_output=True, text=True, env=inv.env)
        r = call("Write", {"file_path": str(self.tmp / "tests/test_a.py"), "content": "x"})
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(call("Write", {"file_path": str(self.tmp / "src/a.py"), "content": "x"}).returncode, 0)
        self.assertEqual(call("Bash", {"command": "git push origin main"}).returncode, 2)

    def test_other_engines_and_fake(self):
        d = self.tmp / "run"; d.mkdir()
        cfg = models.validate_config({"project": "x"})
        kw = dict(role="build", worktree=self.tmp, prompt="P", prompt_file=d / "p.md", run_dir=d,
                  cfg=cfg, frozen=[])
        self.assertEqual(engines.build_invocation("hermes", **kw).argv,
                         ["hermes", "-p", "factory-coder", "-z", "P", "--yolo", "--accept-hooks"])
        self.assertEqual(engines.build_invocation("agy", **kw).argv,
                         ["agy", "-p", "P", "--dangerously-skip-permissions"])
        c = engines.build_invocation("codex", **kw).argv
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", c)  # default: needs docker + git
        self.assertEqual(c[-1], "-")
        ws = models.validate_config({"project": "x", "engines": {"codex": {"sandbox": "workspace-write"}}})
        c2 = engines.build_invocation("codex", **{**kw, "cfg": ws}).argv
        self.assertIn("workspace-write", c2)
        ro = engines.build_invocation("codex", **{**kw, "read_only": True}).argv
        self.assertIn("read-only", ro)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", ro)
        with self.assertRaises(ValueError):
            engines.build_invocation("fake", **kw)
        self.assertEqual(engines.other_vendor("codex"), "claude")
        self.assertEqual(engines.resolve_review_engine("cross", "claude"), "codex")


INTAKE_OK = {"decision": "needs_clarification", "assumptions": ["a"],
             "questions": [{"id": "Q1", "question": "q?", "rationale": "r", "blocking": True,
                            "source_excerpt": "x"}]}


class IntakeTests(CoreCase):
    def src(self, name="spec.md", text="# Spec\nbuild a thing\n"):
        p = self.tmp / name
        p.write_text(text)
        return p

    def intake(self, body, **kw):
        from factory.intake import run_intake
        self.fake(body)
        return run_intake(self.src(**kw), "fake")

    def test_needs_clarification_is_success(self):
        r = self.intake(f"pathlib.Path(os.environ['FACTORY_LAST_MESSAGE']).write_text({json.dumps(json.dumps(INTAKE_OK))!s})")
        self.assertEqual(r["status"], "needs_clarification", r.get("reason"))
        self.assertEqual(r["report"]["questions"][0]["id"], "Q1")
        self.assertTrue(os.path.exists(os.path.join(r["run_dir"], "result.json")))

    def test_read_only_mutation_rejected(self):
        body = (f"pathlib.Path(os.environ['FACTORY_LAST_MESSAGE']).write_text({json.dumps(json.dumps(INTAKE_OK))})\n"
                "pathlib.Path('impl.py').write_text('x = 1')")
        r = self.intake(body)
        self.assertEqual(r["status"], "failed")
        self.assertIn("read-only", r["reason"])

    def test_source_modification_rejected(self):
        body = (f"pathlib.Path(os.environ['FACTORY_LAST_MESSAGE']).write_text({json.dumps(json.dumps(INTAKE_OK))})\n"
                "pathlib.Path('intake.txt').write_text('changed')")
        self.assertEqual(self.intake(body)["status"], "failed")

    def test_contradictory_report_rejected(self):
        bad = dict(INTAKE_OK, decision="ready_for_planning")
        r = self.intake(f"pathlib.Path(os.environ['FACTORY_LAST_MESSAGE']).write_text({json.dumps(json.dumps(bad))})")
        self.assertEqual(r["status"], "failed")
        self.assertIn("contradicts", r["reason"])

    def test_docx_and_bad_extension(self):
        p = self.tmp / "s.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello docx</w:t></w:r></w:p></w:body></w:document>')
        from factory.intake import extract_source
        self.assertEqual(extract_source(p), "Hello docx")
        with self.assertRaises(ValueError):
            extract_source(self.tmp / "a.pdf")

    def test_hermes_has_no_read_only_mode(self):
        from factory.intake import run_intake
        r = run_intake(self.src(), "hermes")
        self.assertEqual(r["status"], "failed")


def cli(*args, env=None, cwd=None):
    e = {**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}
    p = subprocess.run([sys.executable, "-m", "factory", *args], capture_output=True, text=True,
                       env=e, cwd=cwd or str(ROOT))
    return p


class CliTests(CoreCase):
    def test_wait_exit_codes(self):
        self.make_repo()
        rd = state.run_dir("demo", "r-pass"); rd.mkdir(parents=True)
        (rd / "status.json").write_text(json.dumps({"state": "passed"}))
        (rd / "result.json").write_text(json.dumps({"run_id": "r-pass", "passed": True, "status": "passed"}))
        args = ["--repo", str(self.repo)]
        self.assertEqual(cli("wait", "r-pass", *args).returncode, 0)
        rd = state.run_dir("demo", "r-fail"); rd.mkdir()
        (rd / "status.json").write_text(json.dumps({"state": "failed"}))
        (rd / "result.json").write_text(json.dumps({"run_id": "r-fail", "passed": False, "status": "failed", "checks": []}))
        self.assertEqual(cli("wait", "r-fail", *args).returncode, 1)
        dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
        rd = state.run_dir("demo", "r-crash"); rd.mkdir()
        (rd / "status.json").write_text(json.dumps({"state": "running", "pid": dead.pid}))
        self.assertEqual(cli("wait", "r-crash", *args).returncode, 3)
        rd = state.run_dir("demo", "r-run"); rd.mkdir()
        (rd / "status.json").write_text(json.dumps({"state": "running", "pid": os.getpid()}))
        self.assertEqual(cli("wait", "r-run", "--max", "0.2", *args).returncode, 10)

    def test_detached_run_then_wait(self):
        self.make_repo()
        self.fake(GOOD)
        env = {"FACTORY_HOME": os.environ["FACTORY_HOME"], "FACTORY_FAKE_ENGINE": os.environ["FACTORY_FAKE_ENGINE"],
               **{k: v for k, v in os.environ.items() if k.startswith("GIT_")}}
        r = cli("run", "--milestone", "M1", "--role", "build", "--engine", "fake", "--detach",
                "--repo", str(self.repo), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = json.loads(r.stdout)["run_id"]
        w = cli("wait", rid, "--max", "60", "--repo", str(self.repo), env=env)
        self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
        self.assertTrue((self.repo / "src/feature.txt").exists())

    def test_foreground_run_fail_exit_1_and_gate_cmd(self):
        self.make_repo()
        self.fake("pass")
        env = {"FACTORY_HOME": os.environ["FACTORY_HOME"], "FACTORY_FAKE_ENGINE": os.environ["FACTORY_FAKE_ENGINE"]}
        r = cli("run", "--milestone", "M1", "--role", "build", "--engine", "fake", "--attempts", "1",
                "--repo", str(self.repo), env=env)
        self.assertEqual(r.returncode, 1, r.stdout)
        out = json.loads(r.stdout)
        self.assertEqual(out["failed_checks"][0]["id"], "verify")
        g = cli("gate", "--milestone", "M1", "--repo", str(self.repo), env=env)
        self.assertEqual(g.returncode, 1)
        self.assertFalse(json.loads(g.stdout)["ok"])

    def test_init_plan_add_note_status(self):
        r = self.repo
        r.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
        (r / "README.md").write_text("x")
        git(r, "add", "-A"); git(r, "commit", "-q", "-m", "i")
        env = {"FACTORY_HOME": os.environ["FACTORY_HOME"], **{k: v for k, v in os.environ.items() if k.startswith("GIT_")}}
        self.assertEqual(cli("init", "--project", "p1", "--stack", "host", "--reason", "x", "--repo", str(r), env=env).returncode, 0)
        self.assertEqual(cli("init", "--project", "p2", "--stack", "host", "--repo", str(self.tmp), env=env).returncode, 2)  # reason required
        self.assertEqual(git(r, "status", "--porcelain"), "")  # config committed
        (r / ".factory/plan.json").write_text(json.dumps(PLAN))
        git(r, "add", "-A"); git(r, "commit", "-q", "-m", "plan")
        a = cli("plan", "add", "M7", "--goal", "fix stuff", "--verify-as", "M2", "--repo", str(r), env=env)
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(cli("plan", "add", "M7", "--goal", "dup", "--repo", str(r), env=env).returncode, 2)
        self.assertEqual(cli("note", "hand-fixed config", "--repo", str(r), env=env).returncode, 0)
        s = json.loads(cli("status", "--repo", str(r), env=env).stdout)
        self.assertEqual(s["interventions"], 1)
        self.assertEqual(s["extra_milestones"], ["M7"])

    def test_doctor_runs(self):
        r = cli("doctor", env={"FACTORY_HOME": str(self.tmp / "h")})
        self.assertIn(r.returncode, (0, 1))
        self.assertIn("checks", json.loads(r.stdout))

    def test_freeze_cli_twice_rejected(self):
        self.make_repo(freeze=False, holdout=True)
        env = {"FACTORY_HOME": os.environ["FACTORY_HOME"], **{k: v for k, v in os.environ.items() if k.startswith("GIT_")}}
        self.assertEqual(cli("freeze", "--repo", str(self.repo), env=env).returncode, 0)
        self.assertEqual(cli("freeze", "--repo", str(self.repo), env=env).returncode, 2)
        s = state.load_state("demo")
        self.assertTrue(s["freeze_sha"])
        self.assertEqual(s["holdout_files"], ["tests/holdout/h.txt"])


class PipelineTests(CoreCase):
    def test_pipeline_stops_at_checkpoint_then_resumes(self):
        from factory.pipeline import run_pipeline
        self.make_repo()
        self.fake(GOOD)
        s = run_pipeline("demo")
        self.assertEqual(s["status"], "checkpoint")
        self.assertEqual(s["stopped_at"], "M2")  # M2 has checkpoint: true
        self.assertEqual([m["milestone"] for m in s["milestones"]], ["M1", "M2"])
        self.assertEqual(sorted(state.load_state("demo")["done"]), ["M1", "M2"])
        s2 = run_pipeline("demo")
        self.assertEqual(s2["status"], "completed")
        self.assertEqual([m["milestone"] for m in s2["milestones"]], ["M3"])

    def test_pipeline_stops_on_red(self):
        from factory.pipeline import run_pipeline
        self.make_repo()
        self.fake("pass")
        s = run_pipeline("demo")
        self.assertEqual(s["status"], "red")
        self.assertEqual(s["stopped_at"], "M1")
        self.assertEqual(len(s["milestones"]), 1)

    def test_pipeline_next_and_unfrozen_and_missing_engine(self):
        from factory.pipeline import run_pipeline
        self.make_repo()
        self.fake(GOOD)
        s = run_pipeline("demo", next_only=True)
        self.assertEqual((s["status"], len(s["milestones"])), ("stopped", 1))
        os.environ.pop("FACTORY_FAKE_ENGINE")
        self.assertEqual(run_pipeline("demo")["status"], "engine_unavailable")

    def test_pipeline_not_frozen(self):
        from factory.pipeline import run_pipeline
        self.make_repo(freeze=False)
        self.assertEqual(run_pipeline("demo")["status"], "not_frozen")

    def test_pipeline_runs_follow_up_milestone(self):
        from factory.pipeline import run_pipeline
        self.make_repo()
        self.fake(GOOD)
        run_pipeline("demo"); run_pipeline("demo")
        state.update_state("demo", lambda s: s["extra_milestones"].update(
            {"M9": {"id": "M9", "title": "f", "goal": "g", "acceptance": ["a"],
                    "allowed_paths": ["src/"], "verify_as": "M3"}}))
        s = run_pipeline("demo")
        self.assertEqual(s["status"], "completed")
        self.assertEqual([m["milestone"] for m in s["milestones"]], ["M9"])


if __name__ == "__main__":
    unittest.main()
