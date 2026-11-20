import contextlib
import io
import json
from unittest.mock import patch

from core_support import CONFIG, CoreCase
from factory import cli, pipeline
from factory.models import ConfigError, validate_config


class EngineRoutingTests(CoreCase):
    def test_configured_cross_routes_claude_to_hermes(self):
        cfg = validate_config({"project": "demo", "cross": {"claude": "hermes"}})
        self.assertEqual(pipeline.pick_reviewer({}, cfg, "claude"), "hermes")
        self.assertEqual(pipeline.pick_reviewer({"reviewer": "agy"}, cfg, "claude"), "agy")
        with self.assertRaisesRegex(ConfigError, "codex"):
            pipeline.pick_reviewer({}, cfg, "codex")

    def test_cross_map_rejects_self_and_unknown_engines(self):
        for mapping in ({"claude": "claude"}, {"claude": "bad"}, {"bad": "hermes"}):
            with self.subTest(mapping=mapping), self.assertRaises(ConfigError):
                validate_config({"project": "demo", "cross": mapping})

    def test_intake_defaults_to_configured_architect(self):
        self.make_repo(config={**CONFIG, "roles": {"architect": "claude"}}, freeze=False)
        with patch("factory.intake.run_intake", return_value={"status": "ready_for_planning"}) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["intake", "handoff.md", "--repo", str(self.repo)])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.args[1], "claude")

    def test_m0_uses_configured_architect_and_reviewer(self):
        self.make_repo(config={**CONFIG, "roles": {"architect": "claude", "review": "cross"},
                               "cross": {"claude": "hermes"}}, freeze=False)
        out = io.StringIO()
        with patch("factory.runner.execute_run", return_value={"run_id": "test", "status": "passed", "passed": True}) as run:
            with contextlib.redirect_stdout(out):
                rc = cli.main(["run", "--milestone", "M0", "--role", "build",
                               "--review-engine", "configured", "--repo", str(self.repo)])
        self.assertEqual(rc, 0, json.loads(out.getvalue()))
        self.assertEqual(run.call_args.args[3], "claude")
        self.assertEqual(run.call_args.kwargs["review_engine"], "hermes")
