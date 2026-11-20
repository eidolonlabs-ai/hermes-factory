import json
from unittest.mock import patch

from core_support import CoreCase
from factory import engines, runner, state, usage


class EngineUsageTests(CoreCase):
    def test_hermes_reads_per_attempt_report_even_when_review_failed(self):
        report = self.tmp / "review-usage.json"
        report.write_text(json.dumps({"failed": True, "estimated_cost_usd": 1.0,
            "input_tokens": 11, "output_tokens": 22, "cache_read_tokens": 33, "cache_write_tokens": 44,
            "auxiliary": {"input_tokens": 2, "output_tokens": 3},
            "total_including_auxiliary": {"estimated_cost_usd": 1.25}}))
        actual = usage.hermes_usage(report)
        self.assertEqual(actual["tokens"], {"input": 13, "output": 25, "cache_read": 33, "cache_write": 44})
        self.assertEqual(actual["cost_usd"], 1.25)

    def test_missing_or_malformed_hermes_usage_is_unknown(self):
        report = self.tmp / "review-usage.json"
        self.assertEqual(usage.hermes_usage(report), {})
        report.write_text("interrupted write {")
        self.assertEqual(usage.hermes_usage(report), {})

    def test_hermes_usage_rejects_oversized_and_nested_reports(self):
        report = self.tmp / "review-usage.json"
        report.write_text(" " * (1024 * 1024) + '{"estimated_cost_usd": 1}')
        self.assertEqual(usage.hermes_usage(report), {})
        report.write_text("[" * 5000 + "0" + "]" * 5000)
        self.assertEqual(usage.hermes_usage(report), {})

    def test_hermes_reviewer_cli_report_is_recorded(self):
        import os
        import sys

        self.make_repo()
        self.fake("from pathlib import Path\nPath('src/feature.txt').write_text('ok')\n")
        hermes = self.tmp / "hermes"
        hermes.write_text(f"#!{sys.executable}\n"
                          "import json, pathlib, sys\n"
                          "if '--help' in sys.argv:\n"
                          "    print('--usage-file PATH'); sys.exit(0)\n"
                          "path = pathlib.Path(sys.argv[sys.argv.index('--usage-file') + 1])\n"
                          "path.write_text(json.dumps({'estimated_cost_usd': 2.5, 'input_tokens': 19}))\n")
        hermes.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(self.tmp) + os.pathsep + os.environ["PATH"]}):
            result = self.run_ms(review_engine="hermes")
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["history"][-1]["engine"], "hermes")
        self.assertEqual(result["cost_usd"], 2.5)
        self.assertEqual(result["tokens"], {"input": 19})

    def test_claude_usage_reads_cache_breakdown(self):
        log = self.tmp / "log"
        log.write_text(json.dumps({"type": "result", "total_cost_usd": 1.5, "usage": {
            "input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 4}}))
        self.assertEqual(engines.parse_output("claude", log, None)["tokens"],
                         {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4})

    def test_reviewer_usage_is_included_in_project_budget(self):
        self.make_repo()
        self.fake("from pathlib import Path\nPath('src/feature.txt').write_text('ok')\n")
        data = {"cost_usd": 6.5, "tokens": {"input": 5, "output": 6}}
        with patch("factory.engines.parse_output", side_effect=[{}, data]):
            result = self.run_ms(review_engine="fake")
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["cost_usd"], 6.5)
        self.assertEqual(result["tokens"], {"input": 5, "output": 6})
        self.assertEqual(result["usage_incomplete_attempts"], 1)
        self.assertEqual(state.load_state("demo")["cost_usd"], 6.5)
        self.assertEqual(state.load_state("demo")["tokens"], result["tokens"])
        with patch("factory.engines.parse_output", return_value=data):
            next_run = self.run_ms("M2", review_engine="fake")
        self.assertEqual(next_run["status"], "budget")
        self.assertEqual(next_run["attempts"], 1)
