"""End-to-end gate in compose mode: a real Postgres stack, tests inside the compose network.

Skipped when Docker is unavailable. Uses a unique project name and checks nothing is left.
"""
import json
import os
import subprocess
import unittest

from core_support import CONFIG, PLAN, CoreCase, git

from harness import compose

COMPOSE = """
services:
  db:
    image: postgres:16-alpine
    environment: {POSTGRES_PASSWORD: pw}
    healthcheck: {test: ["CMD-SHELL", "pg_isready -U postgres"], interval: 2s, timeout: 3s, retries: 30}
  test:
    image: postgres:16-alpine
    profiles: ["test"]
    volumes: ["./:/src:ro"]
    working_dir: /src
    depends_on: {db: {condition: service_healthy}}
    environment: {PGPASSWORD: pw}
"""
# verify passes only if the feature file exists AND the live database answers from inside
# the compose network (no published ports).
VERIFY = """#!/bin/sh
set -e
test -f src/feature.txt
dc() { docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.yaml "$@"; }
dc up -d --wait --wait-timeout 120 >"$HARNESS_ARTIFACTS/up.log" 2>&1
dc --profile test run --rm -T test psql -h db -U postgres -tAc 'select 41+1' | grep -q 42
"""
HOLDOUT = """#!/bin/sh
docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.yaml --profile test run --rm -T test \
  psql -h db -U postgres -tAc 'select 1' | grep -q 1
"""


@unittest.skipUnless(compose.docker_available()[0], "docker not available")
class ComposeGateTest(CoreCase):
    def make_compose_repo(self, compose_text=COMPOSE):
        cfg = json.loads(json.dumps(CONFIG))
        cfg["stack"] = {"type": "compose", "file": "compose.yaml"}
        cfg["verify"]["timeout_min"] = 5
        cfg["holdout"]["enabled"] = False
        plan = json.loads(json.dumps(PLAN))
        r = self.make_repo(config=cfg, plan=plan, freeze=False, verify=VERIFY)
        (r / "compose.yaml").write_text(compose_text)
        (r / "scripts/holdout.sh").write_text(HOLDOUT)
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "compose stack")
        from harness import holdout
        holdout.freeze(r, "demo")
        return r

    def leftover(self):
        out = subprocess.run(["docker", "ps", "-a", "--format", "{{.Label \"com.docker.compose.project\"}}"],
                             capture_output=True, text=True).stdout.split()
        return [p for p in out if p.startswith("demo-")]

    def test_real_stack_gate_passes_and_tears_down(self):
        self.make_compose_repo()
        self.fake("pathlib.Path('src/feature.txt').write_text('ok')\n")
        res = self.run_ms("M1")
        if not res["passed"]:
            logs = sorted((self.tmp / "home").rglob("verify.log"))
            self.fail(json.dumps(res["checks"], indent=1)[:2000] + "\n" +
                      "\n".join(p.read_text()[-1500:] for p in logs))
        checks = {c["id"]: c for c in res["checks"]}
        self.assertEqual(checks["compose-policy"]["status"], "PASS")
        self.assertEqual(checks["verify"]["status"], "PASS")
        self.assertEqual(checks["compose-teardown"]["status"], "PASS")
        self.assertEqual(self.leftover(), [])

    def test_policy_rejects_published_ports_and_container_name(self):
        bad = COMPOSE.replace("    image: postgres:16-alpine\n    environment: {POSTGRES_PASSWORD: pw}",
                              "    image: postgres:16-alpine\n    container_name: fixed\n"
                              "    ports: [\"5432:5432\"]\n    environment: {POSTGRES_PASSWORD: pw}", 1)
        self.make_compose_repo(bad)
        self.fake("pathlib.Path('src/feature.txt').write_text('ok')\n")
        res = self.run_ms("M1", attempts=1)
        checks = {c["id"]: c for c in res["checks"]}
        self.assertEqual(checks["compose-policy"]["status"], "FAIL")
        self.assertEqual(checks["verify"]["status"], "NOT_RUN")
        self.assertEqual(self.leftover(), [])


if __name__ == "__main__":
    unittest.main()
