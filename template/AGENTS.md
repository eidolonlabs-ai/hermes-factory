# Agent rules for this repository

This repository is built by unattended coding agents, milestone by milestone, and judged by
an external gate (see `CONTRACT.md` in hermes-factory). Requirements are in
`inputs/HANDOFF.md` and `inputs/CLARIFICATIONS.md`; host constraints in
`inputs/ENVIRONMENT.md`; the technical spec in `SPEC.md`; the milestone plan in
`.factory/plan.json`.

## Working unattended
- No human is available during a run. Never ask questions or wait for approval.
- Ambiguity: choose the simplest interpretation consistent with the requirements, append it
  to `RFI.md` (question / decision / reason), and continue.
- Stay inside the milestone's `allowed_paths`. Changes elsewhere fail the gate.

## Done means verified
- A milestone is done only when `scripts/verify.sh <MILESTONE>` exits 0 on a fresh stack.
  Your own report is not evidence; the gate re-runs everything.
- Files listed under `frozen` in `.factory/plan.json` are immutable after checkpoint 1.
  Never edit, rename, skip or delete them. Add new test files instead, tagged with an
  existing milestone so `verify.sh` runs them.
- Bugs found in review: write a failing test first, then fix the root cause.
- Never weaken a test, add retries/sleeps to make a test pass, or mock the database.

## Real stack, end to end
- Everything runs in Docker Compose (`compose.yaml`): databases, API, web app, and the test
  services. Integration tests talk to the live services; E2E tests drive the live UI with
  Playwright inside the `e2e` service.
- Services find each other by compose service name (`db`, `api`, `web`). The web app calls
  the API through a relative path (e.g. `/api/...`) proxied by the web server, so the same
  build works inside the compose network and in a published preview.
- Do not set `container_name`, publish host ports, mount the Docker socket, use privileged
  containers, or bind-mount anything outside the repository. Port publishing for humans lives
  in `compose.preview.yaml` only.
- Only touch the compose project named in `$COMPOSE_PROJECT_NAME`. Never prune or remove
  anything else (`docker system prune` is blocked).

## Context hygiene
- Redirect verbose output (builds, installs, test runs) to log files under
  `${FACTORY_ARTIFACTS:-/tmp}`; read exit codes and `tail` only.

## Git
- Commit at the end of the milestone with conventional messages (`feat(m2): ...`,
  `fix(m3): ...`). Never push, never rewrite history, never use `--no-verify`.
