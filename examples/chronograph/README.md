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

Audit method and findings: `build/results/audit-2026-11-16.md` (four read-only cross-vendor
audits, deduplicated, high findings live-verified).

To reproduce with this harness: copy `build/inputs/*` into a fresh project created from the
template and follow your platform's `PLAYBOOK.md`. Run each orchestrator from the same inputs
and record interventions with `harness note`.
