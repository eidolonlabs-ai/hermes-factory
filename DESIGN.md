# hermes-agent-factory — Design

Status: v0.4 (implemented: CLI, gate, guard, compose, Hermes layer; live-checked hooks). Hermes-native. Sibling repos: `agy-software-factory` (Antigravity),
`codex-factory-template` (Codex). Rules shared between them live in `CONTRACT.md`.

## 1. Purpose

A GitHub template repository for a solo developer: hand Hermes a spec, answer its questions,
approve a plan, and let it build for hours, milestone by milestone, without clicking
"approve". Hermes orchestrates; Claude Code, Codex, Hermes itself (and optionally Antigravity)
build and review. Whether a milestone is done is decided by exit codes, never by an LLM saying so.

### Goals
- One definition of done (`CONTRACT.md`): frozen tests + `scripts/verify.sh <milestone>` +
  holdouts, judged by exit codes.
- Unattended: each run happens in a disposable git worktree; engines run sandboxed where they
  can for read-only work, bypass flags only inside factory worktrees (builders need Docker). You are interrupted only at checkpoints.
- Cross-vendor review by default: the reviewer is not the vendor that built the milestone.
- Uses Hermes natively: skills, profiles, shell hooks, kanban, cron, notifications,
  `delegate_task`, `clarify`, the browser.
- Works for new projects ("Use this template") and existing repos (`factory init`).
- **Docker Compose is required.** The gate boots the real stack (database, API, web app, …)
  and tests it end to end: integration tests hit real services, Playwright drives the real UI.
  No mocked databases in gate tests.

### Non-goals
- Team/org rollout, CI fan-out, signed evidence, promotion pipelines.
- A security sandbox. Isolation protects against **mistakes**, not a malicious agent (§9).
- Replacing Claude/Codex/Antigravity-native factoryes; those have their own repos.

## 2. Pieces

```
┌ Hermes (orchestrator) — your chat session, a kanban card, or a cron job
│   skills: factory (driver), factory-worker (kanban mode); profiles factory-worker
│   (kanban card operator, never codes) and factory-coder (Hermes as a coding engine)
├ factory CLI (Python 3.11+ stdlib) — deterministic: intake, plan, freeze, run, gate, review,
│   pipeline, audit, status, note. State in ~/.hermes/factory/ (outside every repo)
├ Engines — claude -p · codex exec · hermes -p factory-coder -z · agy -p (optional)
└ Project — AGENTS.md (+CLAUDE.md link), SPEC.md, inputs/, scripts/verify.sh, tests/,
    .factory/config.json, .factory/plan.json
```

The CLI is the only thing that decides pass/fail. Hermes drives it, reads its JSON, talks to
you, and does the judgement work (interview, visual check, explaining failures).

## 3. Repository layout

```
hermes-agent-factory/
├─ README.md  DESIGN.md  CONTRACT.md  LICENSE (MIT)
├─ template/                       ← copied into a project by `factory init`
│   ├─ AGENTS.md  CLAUDE.md -> AGENTS.md  SPEC.md  compose.yaml
│   ├─ inputs/{HANDOFF,CLARIFICATIONS,ENVIRONMENT}.md
│   ├─ scripts/verify.sh  scripts/holdout.sh
│   └─ .factory/config.json
├─ factory/                        ← CLI package (`python3 -m factory`, or `factory`)
│   ├─ cli  runner  gate  engines  workspace  process  holdout  guard  compose_policy
│   ├─ audit_diff  detect  models  evidence
│   └─ prompts/{intake,architect,architect_review,build,review}.md
├─ hermes/plugin/                  ← Hermes plugin `factory` (installable on its own)
│   ├─ plugin.yaml  __init__.py           ← pre_tool_call guard, pre_verify nudge
│   └─ skills/{factory,factory-worker}/   ← also copied into the skill index by `factory setup`
├─ profiles/{factory-coder,factory-worker}/   ← profile.json + SOUL.md (role); `factory setup` applies them
├─ pyproject.toml                  ← `uv tool install` / `pipx`: `factory`, `factory-hook`
├─ contract/                       ← shared with sibling repos
│   └─ guard-cases.json  plan.schema.json  result.schema.json
├─ examples/chronograph/           ← intake + build benchmarks
├─ tests/                          ← self-tests with fake engines (unittest)
└─ install.sh                      ← engine (uv/pipx) + `factory setup`
```

The factory is a tool, not a repo to fork: install it once per machine and run `factory init`
in any project repo. Three layers, each replaceable on its own:

| Layer | Where | Installed by |
|---|---|---|
| Engine (`factory`, `factory-hook`; stdlib only) | isolated tool venv | `uv tool install` / `pipx` |
| Hermes side (skills, profiles, guard plugin) | `$HERMES_HOME` | `factory setup` |
| Project files (`template/`) | each project repo | `factory init` |

A wheel carries `template/`, `hermes/plugin/` and `profiles/` under `factory/_data/`
(`factory/resources.py` falls back to the repo folders in a checkout). The plugin never
imports the engine; it calls `factory-hook` on PATH, so
`hermes plugins install owner/repo/hermes/plugin` works for the plugin alone.

Profiles are created by cloning the active profile (`hermes profile create --clone`), not as
Hermes profile distributions: a distribution installs without a model or keys, and a coding
engine that cannot run until someone configures it defeats "install and go".

## 4. Lifecycle

1. **Intake** — drop a spec in chat (or attach it to a kanban card). Hermes runs
   `factory intake SOURCE --engine codex|claude`: a **read-only** architect returns structured
   questions (`needs_clarification` counts as success). Hermes asks you the blocking ones with
   `clarify` and writes `inputs/CLARIFICATIONS.md`.
2. **M0 — contract** — architect engine writes `SPEC.md`, contracts, `scripts/verify.sh`,
   visible tests, holdout tests (`tests/holdout/`) and `.factory/plan.json`. No app logic.
   Cross-vendor review fixes M0 in place.
3. **Checkpoint 1 (you)** — Hermes shows plan, roles, test and holdout counts, open
   questions. On approval: `factory freeze` (frozen hash; holdouts moved to
   `~/.hermes/factory/holdout/<project>/` and removed from the repo).
4. **Milestones** — `factory pipeline` runs, per milestone: worktree → builder → gate →
   cross-vendor review (reproduce-before-fix; screenshot pass for UI) → gate → merge
   (`ff` | `pr` | `human`). Red gate → retry with scrubbed failure tail up to `attempts`;
   then stop, keep the worktree, notify.
5. **Checkpoints** — milestones flagged `checkpoint`, any stop, budget exhaustion. Hermes
   messages you wherever you are (desktop, Telegram, …).
6. **Final** — Hermes reruns the last gate itself, does a browser check, optionally
   `factory audit --engines claude,codex`, reports. Follow-ups: `factory plan add`.

Every human touch is logged with `factory note` (intervention count).

### Two ways to run it
- **Pipeline mode (default)** — in chat, Hermes starts `factory pipeline` as a background
  process with notify-on-exit; you hear back at checkpoints. No board.
- **Kanban mode** — one card per milestone; the `factory-worker` profile claims cards and calls
  the same CLI. For overnight runs, phone intake, or several projects at once.

## 5. Engines

| Engine | Call | Permissions | Guard during the run |
|---|---|---|---|
| Codex | `codex exec -C <wt> --dangerously-bypass-approvals-and-sandbox --json` (intake: `--sandbox read-only`) | bypass, worktree only (default); `engines.codex.sandbox: "workspace-write"` optional | post-hoc checks (no in-agent guard yet) |
| Claude | `claude -p --dangerously-skip-permissions --strict-mcp-config --mcp-config '{"mcpServers":{}}' --settings <run.json> --max-budget-usd N` | bypass, worktree only | PreToolUse guard injected per run via `--settings` (no files in the repo) |
| Hermes | `hermes -p factory-coder -z PROMPT --yolo --accept-hooks`, cwd = worktree | bypass, worktree only | plugin `factory` in the profile: `pre_tool_call` guard (blocks on deny, error, timeout, missing engine), `pre_verify` nudge |
| Antigravity (optional) | `agy -p --dangerously-skip-permissions` | bypass, worktree only | post-hoc checks only |

Review runs use read-only modes where they exist (`codex review --base`, `--sandbox read-only`).
Engine guards save retries; **the gate is the authority** — a missing guard costs time, never
correctness. Structured output: Codex `--output-schema`, Claude `--json-schema`; the factory
validates the JSON itself either way.

## 6. .factory/config.json

```json
{
  "project": "myapp",
  "verify": {"command": "scripts/verify.sh {milestone}", "timeout_min": 40, "require_tests": true},
  "holdout": {"enabled": true, "command": "scripts/holdout.sh {milestone}",
              "feedback": "names_and_messages"},
  "roles": {"architect": "claude", "backend": "codex", "ui": "claude", "review": "cross"},
  "engines": {"claude": {"model": "opus", "max_usd_per_run": 15},
              "codex": {"effort": "high"},
              "hermes": {"profile": "factory-coder"}},
  "budgets": {"attempts": 3, "engine_timeout_min": 90, "run_timeout_min": 240,
              "review_rounds": 2, "project_max_usd": 150},
  "protected": ["tests/", "scripts/verify.sh", "contracts/", ".factory/", "AGENTS.md"],
  "stack": {"type": "compose", "file": "compose.yaml"},
  "merge": "ff",
  "notify": "hermes"
}
```

## 7. Gate

Order, first failure stops (see `CONTRACT.md`):
1. **Scope** — changed paths vs milestone `allowed_paths`; protected-path changes stop for a human.
2. **Frozen** — `git diff <freeze_sha> -- <frozen>` empty and files present.
3. **Hygiene** — no tracked `.env` or private keys; `.env` ignored.
4. **Compose policy** — §8.
5. **Verify** — `verify.command`; `NOT_RUN` never counts as `PASS`; `require_tests`.
6. **Holdouts** — copied in, run, removed in `finally`; builder sees only test ids and
   assertion messages (or counts only).
7. **audit-diff** — file:line findings (secrets, eval/exec, SQL interpolation, XSS sinks);
   high fails, medium is reported.
8. **Candidate hash** — unchanged from the start of the gate.

Gate output: one JSON line + `result.json`; logs stay on disk, only tails go into prompts.

## 8. Compose stack (required)

Every project has a `compose.yaml` describing the whole running system — the services the
app needs (Postgres, Neo4j, Redis, …), the app itself (API, web), and a `test` / `e2e`
service holding the test toolchain (pytest, Playwright). `verify.sh` boots it with
`docker compose up -d --build --wait`, runs integration tests against the live services and
E2E tests against the live UI, then tears it down. A library with no services still gets a
`test` service, so tests run in a clean, reproducible container rather than on the host.

Safety rules, enforced by the runner: unique `COMPOSE_PROJECT_NAME=<project>-<run>`; no published ports during gates (tests run
inside the compose network); policy check on `docker compose config --format json` (rejects
`container_name`, `privileged`, host network, docker socket, bind mounts outside the
worktree, protected project names); teardown in `finally` with a before/after container
snapshot; artifacts copied out first. `factory preview` publishes ports for you and for the
Hermes browser check.

### Opt-out
`"stack": {"type": "host", "reason": "iOS build needs Xcode"}` for projects that cannot run
in Linux containers (iOS/macOS apps, Apple MLX). The reason is required, and every gate report
for such a project says **not isolated**.

## 9. Safety model (honest)

Worktrees, no push, merge only on green: mistakes stay on a disposable branch. Guards block
known-bad commands and writes to protected paths. In bypass mode an agent can still read
anything you can, including the holdout store — holdouts are a discipline that keeps them out
of the repo, prompts and context, not a secret. Engines in containers are a later option.

Hermes serves sessions from one gateway process shared by every profile, so a hook there sees
neither the engine's `FACTORY_*` variables nor a per-profile `HERMES_HOME`. Two consequences:

- The plugin asks Hermes which profile the current turn belongs to (`ctx.profile_name`) and
  guards only `factory-coder` (or a process that does carry `FACTORY_ROOT`). Enabled anywhere
  else it is a no-op.
- The runner registers each live Hermes-engine run in `~/.hermes/factory/active/<run>.json`
  (with its pid). The guard uses the session's working directory when it is a factory
  worktree; otherwise it checks the call against every active run and takes the strictest
  decision. Claude's `--settings` hooks inherit the engine environment directly.

The guard is a plugin hook, not a config.yaml shell hook: no absolute paths in config, no
per-command consent, and it updates with `factory setup`. A plugin callback that raises would
be skipped by Hermes (fail open), so the callback catches everything and returns a block.
`factory setup` refuses to run while a Hermes-engine run is live, because it reloads the plugin.

## 10. factory CLI

```
factory init [--here] | doctor
factory intake SOURCE --engine E           read-only architect → questions JSON
factory freeze
factory run --milestone M --role build|review --engine E [--detach]
factory wait RUN_ID                         0 pass · 1 fail · 3 crashed · 10 running
factory gate --milestone M [--worktree P]
factory pipeline [--until M] [--next]       stops at checkpoints / red / budget
factory plan add M --goal ... --verify-as Mk
factory preview | audit --engines a,b | status | note "text"
```

## 11. Carried over

- **forge / ChronoGraph run:** M0 contract + freeze; cross-vendor review (single-vendor audits
  missed their own vendor's bugs); strict empty MCP config for headless Claude; preflight auth;
  milestone tags on new regression tests; `verify_as` follow-ups; visual pass at 1440x900 and
  390x844 turned into geometry tests.
- **codex-factory-template:** read-only intake with structured questions; argv without shell;
  process-group kill; per-task lock; candidate hash before/after verify and review; review on
  a snapshot commit; atomic `result.json`; strict config validation.
- **agy-software-factory:** guard policy (protected paths, `.env`/keys, shell-write parsing,
  ask on push/reset/clean); `NOT_RUN ≠ PASS`; hygiene; `audit-diff` with SARIF; `detect` to
  seed `verify.sh`.

## 12. v1 test plan

1. Self-tests with fake engines: worktree/merge/keep, frozen tamper, scope, holdout
   copy+scrub+cleanup, retries, budgets, compose policy, teardown, candidate hash.
2. `contract/guard-cases.json` passes against `factory/guard.py`.
3. Live hook checks with tiny prompts: Hermes `pre_tool_call` + `pre_verify`; Claude guard via
   `--settings`.
4. One full live run of `examples/chronograph/build`.

## 13. Later
Engines in containers; PR merge polish; GitHub issue intake; parallel slices with `land`;
`twin` mock server.
