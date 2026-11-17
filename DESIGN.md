# agent-harness — Design

Status: v0.2 (approved direction). Supersedes `agy-software-factory` and
`codex-harness-template`; feature-by-feature mapping in `docs/MIGRATION-MAP.md`.

## 1. Purpose

A GitHub template repository that lets a solo developer hand a spec to an AI coding agent and
let it build for hours, milestone by milestone, without clicking "approve" — while the
decision "is this milestone done?" stays deterministic.

It works with **Claude Code, OpenAI Codex CLI, Google Antigravity (`agy`) and Hermes Agent**.
Any of them can be the orchestrator; any of them can be a builder or reviewer.

**Principle: the harness owns the rules; each platform owns the orchestration.**

### Goals
- One definition of done for every agent: frozen tests + `scripts/verify.sh <milestone>` +
  sealed holdouts, judged by exit codes, never by an LLM's claim.
- Unattended by default: work happens in disposable git worktrees. Engines run in their own
  sandbox where they have one (Codex `workspace-write`, approval `never`); bypass flags are
  used only for engines without a sandbox, and only inside harness worktrees. Humans touch the
  run only at checkpoints.
- Cross-vendor review by default: the agent that reviews a milestone is not the vendor that
  built it.
- Works for new projects ("Use this template") and existing repos (`bootstrap-harness.sh`).
- Optional Docker Compose stack mode with safety rules for running the system under test.

### Non-goals
- Team/org rollout, CI fan-out, DORA metrics, signed evidence or promotion pipelines.
- A security sandbox. Isolation here protects against **mistakes**, not a malicious agent
  (see §9).
- Replacing each platform's native fan-out (subagents, swarms, kanban). Those stay native.

## 2. Layers

```
┌ Orchestration — native per platform (platforms/<name>/)
│   Claude: subagents / agent teams · Codex: exec loop · Antigravity: /goal, /swarm
│   Hermes: pipeline from chat, kanban, cron
├ Core — agent-neutral `harness` CLI (Python stdlib) + guard + prompt contracts
│   plan · freeze · run (worktree→engine→gate→merge) · gate · review · status · compose policy
└ Project — files in each repo
    AGENTS.md, SPEC.md, inputs/, scripts/verify.sh, tests/, .agent-harness/config.json
```

The `harness` CLI is the contract between layers. An orchestrator — or a human in a shell —
asks `harness gate M2` whether a milestone is done and `harness review M2 --engine codex` for a
cold review by another vendor.

## 3. Repository layout

```
agent-harness/
├─ README.md  DESIGN.md  LICENSE (MIT)
├─ AGENTS.md  CLAUDE.md -> AGENTS.md         ← project template (root = what a new project gets)
├─ SPEC.md  inputs/{HANDOFF,CLARIFICATIONS,ENVIRONMENT}.md
├─ scripts/verify.sh  scripts/holdout.sh     ← oracle skeletons
├─ tests/  tests/holdout/
├─ .agent-harness/
│   ├─ config.json                           ← per-project settings (§6)
│   ├─ plan.json                             ← written in M0 (§5)
│   └─ hooks/guard-bash.py                   ← installed copy of the guard
├─ harness/                                  ← core; removed from generated projects
│   ├─ harness.py  (CLI, stdlib only)
│   ├─ guard-bash.py
│   ├─ compose_policy.py
│   └─ prompts/{architect,architect_review,build,review}.md
├─ platforms/
│   ├─ claude/       settings.json hooks, subagents, /milestone command, PLAYBOOK.md
│   ├─ codex/        hooks.json, milestone-loop.sh, PLAYBOOK.md
│   ├─ antigravity/  rules + /goal and /swarm prompt pack, PLAYBOOK.md   (beta)
│   └─ hermes/       skills, shell-hook config, kanban mode, PLAYBOOK.md
├─ examples/chronograph/                    ← HANDOFF + clarifications, benchmark notes
├─ bootstrap-harness.sh                      ← apply to a repo: --platforms claude,codex,...
├─ install.sh                                ← installs `harness` to ~/.agent-harness/
└─ tests/harness/                            ← self-tests with fake engines
```

"Use this template" copies everything; the first `bootstrap-harness.sh --init` in a new
project removes `harness/`, `platforms/` (except selected adapters), `examples/` and the
self-tests, leaving only project files.

Runner state never lives in the project repo: `~/.agent-harness/` holds `state/`, `runs/`,
`worktrees/`, `holdout/`. Coding agents work in worktrees and cannot rewrite the record of
their own runs by editing the repo.

## 4. Lifecycle

1. **Intake** — spec/handoff into `inputs/HANDOFF.md` (chat, file, kanban card, issue).
2. **Interview** — the orchestrator asks clarifying questions one at a time (4-part matrix:
   ordering/duplicates, concurrency, time boundaries, cross-store atomicity); answers go to
   `inputs/CLARIFICATIONS.md`. Host constraints go to `inputs/ENVIRONMENT.md`.
3. **M0 — contract** — architect engine writes `SPEC.md`, contracts, `scripts/verify.sh`,
   visible tests, holdout tests (`tests/holdout/`), and `.agent-harness/plan.json`. No app
   logic. Then a cross-vendor review fixes M0 directly (nothing frozen yet).
4. **Checkpoint 1 (human)** — review plan, test counts, holdout split, RFIs.
   `harness freeze`: visible tests + verify script + contracts become frozen; holdouts are
   moved to `~/.agent-harness/holdout/<project>/` and `git rm`'d from the repo.
5. **Milestones M1..Mn**, each:
   1. create worktree `~/.agent-harness/worktrees/<project>/<run>` on branch `harness/<run>`
   2. builder engine runs (guards active, prompts bypassed)
   3. gate: frozen check → `verify.sh Mk` → holdouts (§7)
   4. reviewer engine (other vendor), fresh context: reproduce-before-fix, visual pass for UI
   5. gate again
   6. fast-forward `main` to the run branch (or open a PR in `merge: pr` mode); remove worktree
   - red gate → retry with the scrubbed failure tail, up to `attempts`; still red → stop,
     keep the worktree, notify.
6. **Checkpoints** — any milestone with `"checkpoint": true`, any stop, budget exhaustion.
7. **Final** — orchestrator runs `harness gate <last>` itself, visual check, optional
   cross-vendor audit (`harness audit`), report.
8. **Follow-ups** — new milestones appended via `harness plan add` (stored in runner state,
   since `plan.json` is frozen), each with `verify_as` naming the existing gate level.

Every human touch is logged with `harness note "<text>"` (intervention count).

## 5. plan.json

```json
{
  "milestones": [
    {"id": "M1", "title": "...", "goal": "...", "acceptance": ["..."],
     "builder": "codex", "reviewer": "claude", "ui": false, "checkpoint": false}
  ],
  "frozen": ["tests/...", "scripts/verify.sh", "contracts/openapi.yaml"],
  "holdout": ["tests/holdout/..."]
}
```

`builder`/`reviewer` default from config roles; `ui: true` turns on the visual review pass.

## 6. .agent-harness/config.json

```json
{
  "project": "myapp",
  "verify": {"command": "scripts/verify.sh {milestone}", "timeout_min": 40},
  "holdout": {"enabled": true, "command": "scripts/holdout.sh {milestone}",
              "feedback": "names_and_messages"},
  "roles": {"backend": "codex", "ui": "claude", "architect": "claude", "review": "cross"},
  "engines": {"claude": {"model": "opus", "effort": "high", "max_usd_per_run": 15},
              "codex": {"effort": "high"},
              "hermes": {"profile": "harness-worker"},
              "agy": {"mode": "auto"}},
  "budgets": {"attempts": 3, "engine_timeout_min": 90, "project_max_usd": 150,
              "review_rounds": 2},
  "stack": {"type": "none"},
  "merge": "ff",
  "notify": {"command": null}
}
```

Compose variant: `"stack": {"type": "compose", "file": "docker-compose.yml",
"protected_projects": [], "preview_ports": {"web": 13000, "api": 18000}}`.

## 7. Gates and holdouts

Gate order (first failure stops): frozen check → compose policy (stack mode) →
`verify.command` → `holdout.command`.

- **Frozen check** — `git diff --name-only <freeze_sha> -- <frozen>` plus existence; any change
  fails the gate. Builders may add new tests (with an existing milestone tag).
- **Holdouts** — at gate time the runner copies `~/.agent-harness/holdout/<project>/` into the
  worktree's `tests/holdout/`, runs the holdout command, captures output to the run dir, and
  deletes the copies in a `finally`. Feedback to the builder is **scrubbed**: test ids and
  assertion messages only (`feedback: names_and_messages`), or pass/fail counts only
  (`counts_only`). Source and tracebacks never reach the builder's prompt.
- **Reviewer** sees holdout failure names too, never holdout source.
- **Cumulative** — `verify.sh Mk` runs everything for M1..Mk; holdouts tagged per milestone
  likewise.

## 8. Docker Compose stack mode (optional)

Ported in slimmed form from the earlier software-factory engine.

- **Unique project per run**: `COMPOSE_PROJECT_NAME=<project>-<runid>`; parallel runs and
  worktrees never share networks or volumes.
- **No host ports during gates**: tests run inside the compose network (backend tests in the
  api container, Playwright in an `e2e` container hitting `http://web:3000`). Published ports
  only in `harness preview` for humans and visual checks.
- **Policy check before boot** (`docker compose config --format json`): reject
  `container_name`, `privileged`, `network_mode: host`, docker socket mounts, bind mounts
  outside the worktree, published ports during gates, protected project names.
- **Teardown in `finally`**: `docker compose -p <name> down -v --remove-orphans`; before/after
  snapshot of containers outside the project must be identical, else the gate fails loudly.
- **Artifacts** (container logs, test reports, screenshots) copied to the run dir before
  teardown.
- `verify.sh` receives `HARNESS_RUN_ID`, `HARNESS_ARTIFACTS`, `COMPOSE_PROJECT_NAME`, and must
  refuse to run destructive compose commands against any other project name.

Projects without services use `"stack": {"type": "none"}`; `verify.sh` just runs the test
commands.

## 9. Safety model (honest)

- Worktrees + no push + ff-only merge on green = mistakes are contained to a disposable branch.
- `guard-bash.py` blocks known-bad commands (push, `--no-verify`, history rewrite, `reset
  --hard`, host-wide prune, `sudo`, `curl | sh`, reading `tests/holdout`, recursive deletes
  outside the repo). Guards are a seatbelt for honest mistakes, not a boundary: with
  bypass-permission modes an agent can still read any file the user can, including the
  holdout store. Holdouts are a **discipline** that removes them from the repo, prompts and
  context; they are not secret.
- Real isolation (running engines in containers) is a future option; config is shaped so it
  can be added without changing the project layout.

## 10. Platform adapters

| | Headless engine call | Guard (pre-command) | "Done" hook | Native orchestration |
|---|---|---|---|---|
| Claude Code | `claude -p --dangerously-skip-permissions --strict-mcp-config --output-format json` | `.claude/settings.json` PreToolUse | Stop → `harness gate` | subagents, agent teams, `/milestone` |
| Codex | `codex exec -C <wt> --dangerously-bypass-approvals-and-sandbox --json` | `.codex/hooks.json` PreToolUse | Stop | exec milestone loop |
| Hermes | `hermes -p harness-worker -z ... --yolo` in the worktree | profile `hooks.pre_tool_call` (`fail_closed`) | `pre_verify`, or `/goal gate add` | pipeline, kanban, cron, delegate_task |
| Antigravity | `agy -p --dangerously-skip-permissions --mode auto` | plugin `hooks.json` PreToolUse (`{decision: deny}`) | plugin Stop (`{decision: continue}`) | `/goal`, `/swarm`, `/teamwork` |

In-agent hooks are a convenience (catch problems early, save retries). **The external gate is
the authority**, which is why Antigravity can participate before its hooks are verified.

To verify before claiming support: Codex repo-level hooks under headless `exec` (trust
requirement; likely `--dangerously-bypass-hook-trust`).

Each `platforms/<name>/PLAYBOOK.md` describes running the milestone loop with that platform as
orchestrator, calling `harness run/gate/review` for the deterministic parts.

## 11. harness CLI

```
harness init            register project, write config, preflight
harness preflight       engine auth, docker, ports, clean tree
harness freeze          freeze visible tests; move holdouts out of the repo
harness run   --milestone M --role build|review --engine E [--detach]
harness wait  RUN_ID    exit 0 pass / 1 fail / 3 crashed / 10 still running
harness gate  --milestone M [--worktree PATH]
harness review --milestone M --engine E          (= run --role review)
harness pipeline [--until M] [--next]            build→gate→review→gate→merge per milestone
harness plan add M6 --goal ... --verify-as M5    follow-up milestones
harness preview         boot the stack with published ports (compose mode)
harness audit --engines claude,codex             read-only cross-vendor audit
harness status | note "<text>"
```

`pipeline` stops at checkpoints, red gates, or budgets; exit status + a summary JSON tell the
orchestrator what happened. Run it in the background and get notified on exit.

## 12. Lessons carried over (from the ChronoGraph comparison)

- A visible-but-frozen suite + cross-vendor review found 15 bugs during the build that the
  builders missed; single-vendor audits miss bugs in that vendor's own code.
- Headless Claude must run with `--strict-mcp-config` and an empty MCP config, or connector
  tool announcements can fill the context and kill long runs.
- Preflight auth: an expired login burns all retries instantly.
- New regression tests must carry an existing milestone tag or the gate never runs them.
- `verify.sh` must lock destructive compose commands to its own project name.
- UI: Playwright is the gate; the reviewer adds a screenshot pass at 1440x900 and 390x844 and
  turns visual bugs into geometry/visibility tests, never pixel diffs.

## 13. Test plan for v1

1. Self-tests with fake engines: worktree create/merge/keep, frozen tamper, holdout copy +
   scrub + cleanup, retries, budget stop, compose policy accept/reject, teardown snapshot.
2. Live hook checks with tiny prompts: Claude PreToolUse + Stop, Codex PreToolUse (headless
   trust), Hermes pre_tool_call + pre_verify. Antigravity marked beta.
3. One full live example run (`examples/chronograph/build`) with one orchestrator.
4. Ported parity suites: 39 agy-software-factory tests, 33 codex-harness-template tests.

## 14. Decisions from the repo merge

1. **Core language: Python 3.11+ stdlib only.** Node code from agy-software-factory (detect,
   check, audit-diff, slices/land, twin, guard tokenizer) is ported, with its tests.
2. **Engine permissions:** sandboxed where supported (Codex `exec --sandbox workspace-write`,
   intake and review `read-only`); Claude/agy/Hermes run with bypass inside the worktree only.
   The runner — not the agent — boots Docker stacks and runs gates on the host.
3. **Merge policy** per project: `ff` (default) | `pr` | `human` (stop at
   `ready_for_human_review`, the codex-harness-template behaviour).
4. **Three layers protect tests:** pre-tool guard (prevent), frozen hash + post-hoc scope /
   protected-path check (detect), holdouts outside the repo (hide).
5. **Run plumbing** from codex-harness-template: argv without shell, process-group kill of
   descendants, per-task lock, candidate hash before/after verify and review, atomic
   `result.json`, review on a snapshot commit in a detached worktree.
6. **Checks from agy-software-factory:** `NOT_RUN` is never `PASS`; `require_tests`; repo
   hygiene (.env, tracked keys); `audit-diff` with SARIF; optional slices with `land`.
   The receipt is a digest, not a signature, and is stored outside the repo.
7. **Intake** is a first-class command (`harness intake --engine E`): read-only architect,
   structured questions JSON, no-mutation check, `needs_clarification` counts as success.
8. **Antigravity is supported** via its plugin format (`hooks.json` PreToolUse/Stop with
   `{decision}` on stdout), proven in agy-software-factory.
9. **Benchmarks:** `examples/chronograph/intake` (master spec, rubric) and
   `examples/chronograph/build` (HANDOFF + clarifications, Antigravity vs Hermes results).

## 15. Out of v1 / later

Engines in containers; PR merge mode polish; GitHub issue
intake; parallel independent milestones.
