# hermes-agent-harness — Design

Status: v0.3. Hermes-native. Sibling repos: `agy-software-factory` (Antigravity),
`codex-harness-template` (Codex). Rules shared between them live in `CONTRACT.md`.

## 1. Purpose

A GitHub template repository for a solo developer: hand Hermes a spec, answer its questions,
approve a plan, and let it build for hours, milestone by milestone, without clicking
"approve". Hermes orchestrates; Claude Code, Codex, Hermes itself (and optionally Antigravity)
build and review. Whether a milestone is done is decided by exit codes, never by an LLM saying so.

### Goals
- One definition of done (`CONTRACT.md`): frozen tests + `scripts/verify.sh <milestone>` +
  holdouts, judged by exit codes.
- Unattended: each run happens in a disposable git worktree; engines run sandboxed where they
  can, bypass flags only inside harness worktrees. You are interrupted only at checkpoints.
- Cross-vendor review by default: the reviewer is not the vendor that built the milestone.
- Uses Hermes natively: skills, profiles, shell hooks, kanban, cron, notifications,
  `delegate_task`, `clarify`, the browser.
- Works for new projects ("Use this template") and existing repos (`harness init`).
- Optional Docker Compose stack mode with safety rules for the system under test.

### Non-goals
- Team/org rollout, CI fan-out, signed evidence, promotion pipelines.
- A security sandbox. Isolation protects against **mistakes**, not a malicious agent (§9).
- Replacing Claude/Codex/Antigravity-native harnesses; those have their own repos.

## 2. Pieces

```
┌ Hermes (orchestrator) — your chat session, a kanban card, or a cron job
│   skills: harness (driver), harness-worker (kanban mode)
├ harness CLI (Python 3.11+ stdlib) — deterministic: intake, plan, freeze, run, gate, review,
│   pipeline, audit, status, note. State in ~/.hermes/harness/ (outside every repo)
├ Engines — claude -p · codex exec · hermes -p harness-worker -z · agy -p (optional)
└ Project — AGENTS.md (+CLAUDE.md link), SPEC.md, inputs/, scripts/verify.sh, tests/,
    .harness/config.json, .harness/plan.json
```

The CLI is the only thing that decides pass/fail. Hermes drives it, reads its JSON, talks to
you, and does the judgement work (interview, visual check, explaining failures).

## 3. Repository layout

```
hermes-agent-harness/
├─ README.md  DESIGN.md  CONTRACT.md  LICENSE (MIT)
├─ template/                       ← copied into a project by `harness init`
│   ├─ AGENTS.md  CLAUDE.md -> AGENTS.md  SPEC.md
│   ├─ inputs/{HANDOFF,CLARIFICATIONS,ENVIRONMENT}.md
│   ├─ scripts/verify.sh  scripts/holdout.sh
│   └─ .harness/config.json
├─ harness/                        ← CLI package (`python3 -m harness`, or `harness`)
│   ├─ cli  runner  gate  engines  workspace  process  holdout  guard  compose_policy
│   ├─ audit_diff  detect  models  evidence
│   └─ prompts/{intake,architect,architect_review,build,review}.md
├─ hermes/
│   ├─ skills/{harness,harness-worker}/SKILL.md
│   ├─ hooks/{guard.py,verify_gate.py}       ← Hermes shell hooks
│   └─ profiles/harness-worker.yaml          ← config fragment (hooks, toolsets)
├─ contract/                       ← shared with sibling repos
│   └─ guard-cases.json  plan.schema.json  result.schema.json
├─ examples/chronograph/           ← intake + build benchmarks
├─ tests/                          ← self-tests with fake engines (unittest)
└─ install.sh                      ← CLI → ~/.local/bin/harness, skills, profile, hooks
```

"Use this template" gives a repo that contains the harness itself; `harness init --here`
moves `template/*` to the root and removes the harness sources. Most users run `install.sh`
once and `harness init` in any repo.

## 4. Lifecycle

1. **Intake** — drop a spec in chat (or attach it to a kanban card). Hermes runs
   `harness intake SOURCE --engine codex|claude`: a **read-only** architect returns structured
   questions (`needs_clarification` counts as success). Hermes asks you the blocking ones with
   `clarify` and writes `inputs/CLARIFICATIONS.md`.
2. **M0 — contract** — architect engine writes `SPEC.md`, contracts, `scripts/verify.sh`,
   visible tests, holdout tests (`tests/holdout/`) and `.harness/plan.json`. No app logic.
   Cross-vendor review fixes M0 in place.
3. **Checkpoint 1 (you)** — Hermes shows plan, roles, test and holdout counts, open
   questions. On approval: `harness freeze` (frozen hash; holdouts moved to
   `~/.hermes/harness/holdout/<project>/` and removed from the repo).
4. **Milestones** — `harness pipeline` runs, per milestone: worktree → builder → gate →
   cross-vendor review (reproduce-before-fix; screenshot pass for UI) → gate → merge
   (`ff` | `pr` | `human`). Red gate → retry with scrubbed failure tail up to `attempts`;
   then stop, keep the worktree, notify.
5. **Checkpoints** — milestones flagged `checkpoint`, any stop, budget exhaustion. Hermes
   messages you wherever you are (desktop, Telegram, …).
6. **Final** — Hermes reruns the last gate itself, does a browser check, optionally
   `harness audit --engines claude,codex`, reports. Follow-ups: `harness plan add`.

Every human touch is logged with `harness note` (intervention count).

### Two ways to run it
- **Pipeline mode (default)** — in chat, Hermes starts `harness pipeline` as a background
  process with notify-on-exit; you hear back at checkpoints. No board.
- **Kanban mode** — one card per milestone; the `harness-worker` profile claims cards and calls
  the same CLI. For overnight runs, phone intake, or several projects at once.

## 5. Engines

| Engine | Call | Permissions | Guard during the run |
|---|---|---|---|
| Codex | `codex exec -C <wt> --sandbox workspace-write -c approval_policy="never" --json --output-schema F` | Codex sandbox | sandbox + post-hoc checks |
| Claude | `claude -p --dangerously-skip-permissions --strict-mcp-config --mcp-config '{"mcpServers":{}}' --settings <run.json> --max-budget-usd N` | bypass, worktree only | PreToolUse guard injected per run via `--settings` (no files in the repo) |
| Hermes | `hermes -p harness-worker -z PROMPT --yolo`, cwd = worktree | bypass, worktree only | profile shell hooks: `pre_tool_call` guard (`fail_closed: true`), `pre_verify` gate |
| Antigravity (optional) | `agy -p --dangerously-skip-permissions` | bypass, worktree only | post-hoc checks only |

Review runs use read-only modes where they exist (`codex review --base`, `--sandbox read-only`).
Engine guards save retries; **the gate is the authority** — a missing guard costs time, never
correctness. Structured output: Codex `--output-schema`, Claude `--json-schema`; the harness
validates the JSON itself either way.

## 6. .harness/config.json

```json
{
  "project": "myapp",
  "verify": {"command": "scripts/verify.sh {milestone}", "timeout_min": 40, "require_tests": true},
  "holdout": {"enabled": true, "command": "scripts/holdout.sh {milestone}",
              "feedback": "names_and_messages"},
  "roles": {"architect": "claude", "backend": "codex", "ui": "claude", "review": "cross"},
  "engines": {"claude": {"model": "opus", "max_usd_per_run": 15},
              "codex": {"effort": "high"},
              "hermes": {"profile": "harness-worker"}},
  "budgets": {"attempts": 3, "engine_timeout_min": 90, "run_timeout_min": 240,
              "review_rounds": 2, "project_max_usd": 150},
  "protected": ["tests/", "scripts/verify.sh", "contracts/", ".harness/", "AGENTS.md"],
  "stack": {"type": "none"},
  "merge": "ff",
  "notify": "hermes"
}
```

## 7. Gate

Order, first failure stops (see `CONTRACT.md`):
1. **Scope** — changed paths vs milestone `allowed_paths`; protected-path changes stop for a human.
2. **Frozen** — `git diff <freeze_sha> -- <frozen>` empty and files present.
3. **Hygiene** — no tracked `.env` or private keys; `.env` ignored.
4. **Compose policy** — stack mode only (§8).
5. **Verify** — `verify.command`; `NOT_RUN` never counts as `PASS`; `require_tests`.
6. **Holdouts** — copied in, run, removed in `finally`; builder sees only test ids and
   assertion messages (or counts only).
7. **audit-diff** — file:line findings (secrets, eval/exec, SQL interpolation, XSS sinks);
   high fails, medium is reported.
8. **Candidate hash** — unchanged from the start of the gate.

Gate output: one JSON line + `result.json`; logs stay on disk, only tails go into prompts.

## 8. Compose stack mode (optional)

Unique `COMPOSE_PROJECT_NAME=<project>-<run>`; no published ports during gates (tests run
inside the compose network); policy check on `docker compose config --format json` (rejects
`container_name`, `privileged`, host network, docker socket, bind mounts outside the
worktree, protected project names); teardown in `finally` with a before/after container
snapshot; artifacts copied out first. `harness preview` publishes ports for you and for the
Hermes browser check.

## 9. Safety model (honest)

Worktrees, no push, merge only on green: mistakes stay on a disposable branch. Guards block
known-bad commands and writes to protected paths. In bypass mode an agent can still read
anything you can, including the holdout store — holdouts are a discipline that keeps them out
of the repo, prompts and context, not a secret. Engines in containers are a later option.

Hermes shell hooks need one-time consent per `(event, command)`; `install.sh` sets
`hooks_auto_accept` only in the dedicated `harness-worker` profile, never in your default
profile.

## 10. harness CLI

```
harness init [--here] | doctor
harness intake SOURCE --engine E           read-only architect → questions JSON
harness freeze
harness run --milestone M --role build|review --engine E [--detach]
harness wait RUN_ID                         0 pass · 1 fail · 3 crashed · 10 running
harness gate --milestone M [--worktree P]
harness pipeline [--until M] [--next]       stops at checkpoints / red / budget
harness plan add M --goal ... --verify-as Mk
harness preview | audit --engines a,b | status | note "text"
```

## 11. Carried over

- **forge / ChronoGraph run:** M0 contract + freeze; cross-vendor review (single-vendor audits
  missed their own vendor's bugs); strict empty MCP config for headless Claude; preflight auth;
  milestone tags on new regression tests; `verify_as` follow-ups; visual pass at 1440x900 and
  390x844 turned into geometry tests.
- **codex-harness-template:** read-only intake with structured questions; argv without shell;
  process-group kill; per-task lock; candidate hash before/after verify and review; review on
  a snapshot commit; atomic `result.json`; strict config validation.
- **agy-software-factory:** guard policy (protected paths, `.env`/keys, shell-write parsing,
  ask on push/reset/clean); `NOT_RUN ≠ PASS`; hygiene; `audit-diff` with SARIF; `detect` to
  seed `verify.sh`.

## 12. v1 test plan

1. Self-tests with fake engines: worktree/merge/keep, frozen tamper, scope, holdout
   copy+scrub+cleanup, retries, budgets, compose policy, teardown, candidate hash.
2. `contract/guard-cases.json` passes against `harness/guard.py`.
3. Live hook checks with tiny prompts: Hermes `pre_tool_call` + `pre_verify`; Claude guard via
   `--settings`.
4. One full live run of `examples/chronograph/build`.

## 13. Later
Engines in containers; PR merge polish; GitHub issue intake; parallel slices with `land`;
`twin` mock server.
