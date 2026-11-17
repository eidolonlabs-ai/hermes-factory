# ChronoGraph benchmark

A temporal knowledge graph app (FastAPI + PostgreSQL + Neo4j + React, Docker Compose) used to
compare agent workflows on identical inputs. Two benchmarks:

## 1. Intake benchmark (`intake/`)
Input: `MASTER-SPEC.md`, the original ChronoGraph master handoff specification, preserved
unchanged. It is **deliberately incomplete and partly contradictory** (e.g. it fixes
`container_name` and host ports, says `:FACT` in one place and `:RELATION` in another, and
leaves out-of-order episodes, re-assertion and retraction undefined).

Task: run `harness intake examples/chronograph/intake/MASTER-SPEC.md --engine <E>`. A good
architect returns `needs_clarification` with source-grounded blocking questions; it must not
build anything or run the embedded scripts. Score with `evaluator/rubric.md` +
`scorecard.json`. **Never give the evaluator files to the architect.**

Earlier results (Codex, from codex-harness-template): `intake/results/`.

## 2. Build benchmark (`build/`)
Inputs: `build/inputs/HANDOFF.md` (the 28-line condensed handoff both reference builds
received) + `CLARIFICATIONS.md` (the product owner's 4 answers given to Antigravity's
`/grill-me`). Nothing else.

| Build | Orchestration | Wall time | Human interventions | Unique audit findings (high) |
|---|---|---|---|---|
| Antigravity (`/goal`, `/run-workflow`) | Antigravity | ~2h37m | 8 | 13 (2) |
| Hermes forge (Claude builds UI, Codex builds backend, cross-vendor review) | Hermes | ~4h17m start to finish incl. the M0 checkpoint (M0 took 55 min) | 2 | 7 (0) |
| **hermes-agent-harness** (same roles; real-stack compose gate, holdouts, diff audit) | Hermes | ~3h30m of build time, excluding waits for approvals | 6 (3 of them harness bugs found by this run) | 4 (1, rated medium by the other vendor) |

Audit method and findings: `build/results/audit-2026-11-16.md` (Antigravity, forge) and
`build/results/audit-2026-11-17-harness.md` (this harness): the same read-only cross-vendor
prompt, deduplicated, findings live-verified where possible.

### The hermes-agent-harness run (2026-11-16/17)

| Milestone | Builder → reviewer | Result |
|---|---|---|
| M0 contract | Claude → Codex | 1st run red: the guard blocked `plan.json`/holdouts (harness bug, fixed); resumed, passed |
| M1 infra + heartbeat | Codex → Claude | stopped: a frozen M0 gate self-test needed `tests/holdout/` (contract bug, fixed with approval); resumed, passed |
| M2 engine + projection | Codex → Claude | passed on attempt 2 (attempt 1: teardown false alarm) |
| M3 query API | Codex → Claude | review went red: the guard froze tests added after freeze (harness bug, fixed); resumed, passed |
| M4 UI | Claude → Codex | passed first attempt |
| M5 UI | Claude → Codex | passed first attempt |

Final independent gate on M5: every check PASS (scope, frozen, hygiene, compose policy,
`verify.sh M5` on the live stack, holdouts, diff audit, candidate hash, teardown).
Tests in the result: 171 visible integration, 42 holdout, 47 Playwright. Claude cost about
$23 (about $9.60 of it was the M0 attempt lost to the guard bug), plus Codex tokens.

What the first real run taught the harness (all fixed, with tests):
1. M0 must be allowed to write `.harness/plan.json` and `tests/holdout/`.
2. A frozen directory freezes the files that existed at freeze; tests added later stay editable.
3. Hermes shell hooks get a scrubbed env and `~/.hermes` as cwd, so the guard finds live runs
   through a registry file.
4. The gate's own self-tests must work with holdouts absent; the architect prompt now says so.
5. Codex needs Docker and git inside its worktree, so it runs with the sandbox bypassed there.
6. Stopping a run must tear down the engine's stack and mark the run interrupted.

To reproduce with this harness: `harness init` in a fresh repo, copy `build/inputs/*` into
`inputs/`, then follow the `harness` skill (or the CLI steps in the top-level README).
Record every human touch with `harness note`.
