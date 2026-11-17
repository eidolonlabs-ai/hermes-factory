import json
import os
import subprocess
import sys
import unittest

from core_support import CoreCase, ROOT, git
from harness import state, workspace

GOOD = """pathlib.Path('src').mkdir(exist_ok=True); pathlib.Path('src/feature.txt').write_text('ok')"""


def check(res, cid):
    return next(c for c in res["checks"] if c["id"] == cid)


class RunnerTests(CoreCase):
    def test_passing_build_merges_ff(self):
        self.make_repo()
        self.fake(GOOD)
        before = git(self.repo, "rev-parse", "HEAD")
        res = self.run_ms()
        self.assertEqual(res["status"], "passed", res.get("summary"))
        self.assertTrue(res["merged"])
        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD"), before)
        self.assertEqual((self.repo / "src/feature.txt").read_text(), "ok")
        self.assertIn("M1", state.load_state("demo")["done"])
        self.assertFalse(os.path.exists(res["worktree"]))
        rdir = state.run_dir("demo", res["run_id"])
        self.assertTrue((rdir / "result.json").exists())
        self.assertEqual(json.loads((rdir / "result.json").read_text())["run_id"], res["run_id"])
        self.assertTrue((rdir / "gate-build-1" / "gate.json").exists())
        self.assertEqual(check(res, "verify")["status"], "PASS")

    def test_failing_build_retries_then_keeps_worktree(self):
        self.make_repo()
        self.fake("pathlib.Path('README.md').write_text('attempt %d' % A)")
        res = self.run_ms()
        self.assertEqual(res["status"], "failed")
        self.assertFalse(res["passed"])
        self.assertEqual(res["attempts"], 2)  # budgets.attempts == 2
        self.assertTrue(os.path.isdir(res["worktree"]))
        self.assertTrue(res["worktree_kept"])
        self.assertNotIn("M1", state.load_state("demo")["done"])
        # retry prompt carries the gate feedback, not the first prompt
        p2 = (state.run_dir("demo", res["run_id"]) / "prompt-build-2.md").read_text()
        self.assertIn("PREVIOUS ATTEMPT FAILED", p2)
        self.assertIn("[verify]", p2)

    def test_retry_succeeds_on_second_attempt(self):
        self.make_repo()
        self.fake(f"if A == 2:\n    {GOOD}")
        res = self.run_ms()
        self.assertEqual(res["status"], "passed")
        self.assertEqual(res["attempts"], 2)

    def test_frozen_tamper_fails_gate(self):
        import copy
        from core_support import PLAN
        plan = copy.deepcopy(PLAN)
        plan["milestones"][0]["allowed_paths"] = ["src/", "spec/"]  # so scope passes, frozen decides
        self.make_repo(plan=plan)
        self.fake(GOOD + "\npathlib.Path('spec/frozen.txt').write_text('tampered')")
        head = git(self.repo, "rev-parse", "HEAD")
        res = self.run_ms(attempts=1)
        self.assertFalse(res["passed"])
        self.assertEqual(check(res, "frozen")["status"], "FAIL")
        self.assertIn("spec/frozen.txt", check(res, "frozen")["details"])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)  # main untouched

    def test_out_of_scope_change_fails(self):
        self.make_repo()
        self.fake(GOOD + "\npathlib.Path('other').mkdir(); pathlib.Path('other/x.txt').write_text('x')")
        res = self.run_ms(attempts=1)
        self.assertFalse(res["passed"])
        self.assertEqual(check(res, "scope")["status"], "FAIL")
        self.assertIn("other/x.txt", check(res, "scope")["details"])
        self.assertEqual(check(res, "verify")["status"], "NOT_RUN")  # first failure stops

    def test_protected_path_change_stops_for_human(self):
        self.make_repo()
        self.fake(GOOD + "\nwith open('scripts/verify.sh', 'a') as f: f.write('# edit\\n')")
        res = self.run_ms()  # 2 attempts allowed, but must stop on the first
        self.assertEqual(res["status"], "needs_human")
        self.assertEqual(res["attempts"], 1)
        self.assertTrue(os.path.isdir(res["worktree"]))

    def test_holdout_copied_in_scrubbed_and_removed(self):
        self.make_repo(holdout=True)
        self.assertFalse((self.repo / "tests/holdout").exists())  # moved out at freeze
        self.assertTrue((state.holdout_store("demo") / "tests/holdout/h.txt").exists())
        # attempt 1 builds the wrong thing (holdout fails), attempt 2 is right
        self.fake("pathlib.Path('src').mkdir(exist_ok=True)\n"
                  "pathlib.Path('src/feature.txt').write_text('bad' if A == 1 else 'ok')")
        res = self.run_ms()
        self.assertEqual(res["status"], "passed", res.get("summary"))
        rdir = state.run_dir("demo", res["run_id"])
        p2 = (rdir / "prompt-build-2.md").read_text()
        self.assertIn("tests/holdout/h.py::test_feature", p2)
        self.assertIn("expected ok", p2)
        self.assertNotIn("SECRET_SOURCE", p2)
        self.assertNotIn("holdout source line", p2)
        gate1 = json.loads((rdir / "gate-build-1" / "gate.json").read_text())
        self.assertNotIn("SECRET_SOURCE", json.dumps(gate1))
        self.assertFalse((self.repo / "tests/holdout").exists())

    def test_holdout_removed_after_failure_in_worktree(self):
        self.make_repo(holdout=True)
        self.fake("pathlib.Path('src').mkdir(exist_ok=True); pathlib.Path('src/feature.txt').write_text('bad')")
        res = self.run_ms(attempts=1)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(check(res, "holdout")["status"], "FAIL")
        self.assertFalse(os.path.exists(os.path.join(res["worktree"], "tests/holdout")))
        self.assertIn("holdouts: 1 failed, 2 passed", check(res, "holdout")["summary"])

    def test_missing_verify_is_not_run_and_fails(self):
        self.make_repo()
        self.fake(GOOD)
        git(self.repo, "rm", "-q", "scripts/verify.sh")
        git(self.repo, "commit", "-q", "-m", "drop verify")
        res = self.run_ms(attempts=1)
        self.assertFalse(res["passed"])
        self.assertEqual(check(res, "verify")["status"], "NOT_RUN")

    def test_not_run_verify_fails_even_when_other_checks_pass(self):
        from harness import gate, models
        cfg = models.validate_config({**__import__("core_support").CONFIG})
        self.make_repo()
        git(self.repo, "rm", "-q", "scripts/verify.sh")
        git(self.repo, "commit", "-q", "-m", "drop")
        ctx = gate.GateContext("demo", self.repo, self.repo, git(self.repo, "rev-parse", "HEAD"),
                               {"id": "M1", "allowed_paths": ["src/"]}, cfg, None, [], "r1", self.tmp / "g")
        ok, checks = gate.run_gate(ctx)
        self.assertFalse(ok)
        self.assertEqual([c.id for c in checks if c.id == "require-tests"], ["require-tests"])

    def test_candidate_changed_during_gate_fails(self):
        v = "#!/bin/sh\ntest -f src/feature.txt || exit 1\necho mutated >> src/feature.txt\n"
        self.make_repo(verify=v)
        self.fake(GOOD)
        res = self.run_ms(attempts=1)
        self.assertFalse(res["passed"])
        self.assertEqual(check(res, "verify")["status"], "PASS")
        self.assertEqual(check(res, "candidate")["status"], "FAIL")

    def test_candidate_hash_stable_and_sensitive(self):
        self.make_repo()
        h1 = workspace.candidate_hash(self.repo)
        self.assertEqual(h1, workspace.candidate_hash(self.repo))
        (self.repo / "src/new.txt").write_text("x")
        self.assertNotEqual(h1, workspace.candidate_hash(self.repo))
        h2 = workspace.candidate_hash(self.repo)
        os.chmod(self.repo / "src/new.txt", 0o755)
        self.assertNotEqual(h2, workspace.candidate_hash(self.repo))

    def test_lock_prevents_concurrent_same_milestone(self):
        self.make_repo()
        self.fake(GOOD)
        lock = workspace.acquire_lock("demo", "M1", "other")
        try:
            res = self.run_ms()
            self.assertEqual(res["status"], "locked")
            self.assertFalse(res["passed"])
            self.run_ms("M2") if False else None
        finally:
            lock.release()
        # different milestone is independent; same milestone works after release
        l2 = workspace.acquire_lock("demo", "M2", "x")
        l2.release()
        self.assertEqual(self.run_ms()["status"], "passed")

    def test_stale_lock_is_taken_over(self):
        self.make_repo()
        d = state.locks_dir("demo")
        d.mkdir(parents=True)
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        (d / "M1.lock").write_text(f"pid={p.pid} run=dead\n")
        self.fake(GOOD)
        self.assertEqual(self.run_ms()["status"], "passed")

    def test_main_moved_fails_merge_and_keeps_worktree(self):
        self.make_repo()
        # engine also advances main while the run is in flight
        self.fake(GOOD + f"\nimport subprocess\nsubprocess.run(['git','-C',{str(self.repo)!r},"
                         "'commit','--allow-empty','-q','-m','moved'], check=True)")
        res = self.run_ms()
        self.assertEqual(res["status"], "failed")
        self.assertIn("moved", res["summary"])
        self.assertTrue(os.path.isdir(res["worktree"]))

    def test_review_runs_in_same_worktree_then_gates_again(self):
        self.make_repo()
        self.fake(GOOD + "\nif ROLE == 'review':\n    pathlib.Path('src/review.txt').write_text('r')")
        res = self.run_ms(review_engine="fake")
        self.assertEqual(res["status"], "passed", res.get("summary"))
        self.assertEqual([h["role"] for h in res["history"]], ["build", "review"])
        self.assertTrue((self.repo / "src/review.txt").exists())

    def test_review_scope_violation_fails(self):
        self.make_repo()
        self.fake(GOOD + "\nif ROLE == 'review':\n    pathlib.Path('evil.txt').write_text('r')")
        res = self.run_ms(review_engine="fake")
        self.assertFalse(res["passed"])
        self.assertEqual(check(res, "scope")["status"], "FAIL")
        self.assertFalse((self.repo / "evil.txt").exists())

    def test_merge_policy_human_does_not_merge(self):
        import copy
        from core_support import CONFIG
        cfg = copy.deepcopy(CONFIG); cfg["merge"] = "human"
        self.make_repo(config=cfg)
        self.fake(GOOD)
        res = self.run_ms()
        self.assertTrue(res["passed"])
        self.assertFalse(res["merged"])
        self.assertFalse((self.repo / "src/feature.txt").exists())
        self.assertIn(res["branch"], git(self.repo, "branch", "--list", "harness/*"))

    def test_unfrozen_project_rejects_non_m0(self):
        self.make_repo(freeze=False)
        self.fake(GOOD)
        res = self.run_ms()
        self.assertEqual(res["status"], "failed")
        self.assertIn("not frozen", res["summary"])

    def test_m0_build_passes_structure_check(self):
        self.make_repo(freeze=False)
        self.fake("pathlib.Path('SPEC.md').write_text('spec')")
        res = self.run_ms("M0")
        self.assertEqual(res["status"], "passed", res.get("summary"))
        self.assertEqual(check(res, "m0-structure")["status"], "PASS")

    def test_extra_milestone_verify_as(self):
        self.make_repo()
        from harness import state as st
        st.update_state("demo", lambda s: s["extra_milestones"].update(
            {"M9": {"id": "M9", "title": "fix", "goal": "g", "acceptance": ["a"],
                    "allowed_paths": ["src/"], "verify_as": "M1"}}))
        self.fake(GOOD)
        res = self.run_ms("M9")
        self.assertEqual(res["status"], "passed", res.get("summary"))
        self.assertIn("scripts/verify.sh M1", check(res, "verify")["summary"])


if __name__ == "__main__":
    unittest.main()
