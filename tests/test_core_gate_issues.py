import contextlib
import io
import json

from core_support import CoreCase, git
from factory import cli, gate, state
from factory.models import load_config


class GateIssueTests(CoreCase):
    def test_audit_finding_arrives_before_verify_can_fail(self):
        self.make_repo()
        (self.repo / "src/query.py").write_text('query = f"SELECT {COLUMNS} FROM records WHERE id = $1"\n')
        st = state.load_state("demo")
        ctx = gate.GateContext("demo", self.repo, self.repo, st["freeze_sha"],
                               {"id": "M1", "allowed_paths": ["src/"]}, load_config(self.repo),
                               st["freeze_sha"], st["frozen"], "test", self.tmp / "out")
        ok, checks = gate.run_gate(ctx)
        self.assertFalse(ok)
        statuses = {c.id: c.status for c in checks}
        self.assertEqual(statuses["audit-diff"], "FAIL")
        self.assertEqual(statuses["verify"], "NOT_RUN")
        feedback = gate.feedback_from_checks(checks)
        self.assertIn("sql-interpolation", feedback)
        self.assertIn("static SQL", feedback)

    def run_gate_cli(self, *args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = cli.main(["gate", "--repo", str(self.repo), *args])
        return rc, json.loads(stdout.getvalue())

    def test_final_gate_audits_changes_from_disjoint_milestones(self):
        plan = {"milestones": [
            {"id": mid, "title": mid, "goal": "ship", "acceptance": ["works"],
             "allowed_paths": [f"{folder}/"]}
            for mid, folder in [("M1", "src"), ("M2", "web")]],
            "frozen": ["scripts/verify.sh"], "holdout": []}
        self.make_repo(plan=plan, verify='#!/bin/sh\ntest "$1" = M2\n')
        (self.repo / "src/backend.txt").write_text("backend\n")
        git(self.repo, "add", "src")
        git(self.repo, "commit", "-m", "backend")
        (self.repo / "web").mkdir()
        (self.repo / "web/frontend.txt").write_text("frontend\n")
        git(self.repo, "add", "web")
        git(self.repo, "commit", "-m", "frontend")
        rc, obj = self.run_gate_cli("--final")
        checks = {c["id"]: c for c in obj["checks"]}
        self.assertEqual(rc, 0, obj)
        self.assertEqual(obj["milestone"], "M2")
        self.assertEqual(checks["scope"]["summary"], "2 changed path(s) within scope")
        self.assertEqual(checks["audit-diff"]["summary"], "no findings in 2 file(s)")
        self.assertEqual(checks["verify"]["status"], "PASS")
        (self.repo / "unplanned.txt").write_text("out of scope\n")
        rc, obj = self.run_gate_cli("--final")
        self.assertEqual(rc, 1, obj)
        self.assertEqual(obj["checks"][0]["status"], "FAIL")

    def test_empty_diff_does_not_report_scope_or_audit_as_pass(self):
        self.make_repo(verify="#!/bin/sh\nexit 0\n")
        rc, obj = self.run_gate_cli("--milestone", "M1", "--base", "HEAD")
        statuses = {c["id"]: c["status"] for c in obj["checks"]}
        self.assertEqual(rc, 0, obj)
        self.assertEqual(statuses["scope"], "NOT_RUN")
        self.assertEqual(statuses["audit-diff"], "NOT_RUN")
        self.assertEqual(statuses["verify"], "PASS")

    def test_final_requires_a_real_diff_audit(self):
        self.make_repo(verify="#!/bin/sh\nexit 0\n")
        rc, obj = self.run_gate_cli("--final")
        self.assertEqual(rc, 1, obj)
        self.assertFalse(obj["ok"])
        self.assertEqual(obj["checks"][-1]["id"], "require-diff")

    def test_milestone_needs_an_explicit_base_without_a_recorded_base(self):
        self.make_repo()
        rc, obj = self.run_gate_cli("--milestone", "M1")
        self.assertEqual(rc, 2, obj)
        self.assertIn("--base", obj["error"])

    def test_invalid_base_revision_is_rejected_before_the_gate(self):
        self.make_repo()
        rc, obj = self.run_gate_cli("--milestone", "M1", "--base", "missing-ref")
        self.assertEqual(rc, 2, obj)
        self.assertIn("baseline", obj["error"])

    def test_final_gate_requires_freeze(self):
        self.make_repo(freeze=False)
        rc, obj = self.run_gate_cli("--final")
        self.assertEqual(rc, 2)
        self.assertIn("factory freeze", obj["error"])
