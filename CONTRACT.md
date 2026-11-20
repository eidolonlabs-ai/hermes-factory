# Factory contract (shared)

The rules every factory in this family follows, whatever the platform: [`antigravity-factory`](https://github.com/eidolonlabs-ai/antigravity-factory), [`claude-factory`](https://github.com/eidolonlabs-ai/claude-factory), [`codex-factory`](https://github.com/eidolonlabs-ai/codex-factory), and [`hermes-factory`](https://github.com/eidolonlabs-ai/hermes-factory) (under [`eidolonlabs-ai`](https://github.com/eidolonlabs-ai)). Each repository implements these rules natively in its own language and with its own platform features. This file and the `contract/` folder are copied between repositories; when a rule changes, update all four.

Version: 1.2

## 1. Definition of done

A milestone or task is done when, and only when, the **gate** for that milestone/task exits 0 on the exact code being merged. The agent's own report ("completed", "all tests pass") is never evidence.

## 2. The gate

Run by the factory, outside the agent's session, on the candidate worktree. Steps, first failure stops:

| # | Step | Fails when |
|---|---|---|
| 1 | Scope | a changed path is outside the milestone's `allowed_paths`, or a protected path changed (stop for a human) |
| 2 | Frozen | any frozen file differs from the freeze commit, or is missing |
| 3 | Hygiene | `.env` or a private key is tracked, or `.env` exists and is not git-ignored |
| 4 | Compose policy | the Compose configuration violates the project's isolation rules |
| 5 | Diff audit | a high-severity finding (secret, dynamic exec, SQL interpolation) in changed files |
| 6 | Verify | `scripts/verify.sh <milestone>` (or configured verification checks) exits non-zero (it boots the real stack, §4) |
| 7 | Holdouts | the holdout command exits non-zero |
| 8 | Candidate hash | the code changed while the gate ran |

Steps a project does not use (no holdouts, no audit) are reported `NOT_RUN`.

## 3. Check results

Every check reports `PASS`, `FAIL` or `NOT_RUN`. **`NOT_RUN` is never `PASS`.** When `require_tests` is on (the default), a gate with no test check that actually ran is a failure. A missing test script, an unreachable Docker daemon, or an empty check list is `NOT_RUN`, not green.

## 4. Real stack, end to end

The gate tests the running system, not a simulation of it. Each project has a Docker Compose file with every service it needs (database, API, web app, …) plus a test service. The gate boots the stack, waits for health checks, runs integration tests against the live services and browser E2E tests (Playwright) against the live UI, and tears the stack down afterwards.

- No mocked databases or in-memory substitutes in gate tests. External third-party APIs may be replaced by a local fake *service* in the compose file.
- Each run uses its own compose project name, network and volumes; no fixed `container_name`, no published host ports during the gate, no Docker socket or privileged containers, no bind mounts outside the project.
- Teardown always runs, and the gate fails if containers outside its own project changed.
- Opt-out only for projects that cannot run in Linux containers, with a written reason; their gate reports say "not isolated".

### Concurrent Multi-Factory Isolation & Default Port Allocation

All four factories can run and preview ChronoGraph (or any Compose app) concurrently on the same host without container name, Compose project name, teardown drift, or host port collisions:

| Factory | Platform ID | Ephemeral Gate `COMPOSE_PROJECT_NAME` | Interactive / Browser Preview Project | Default Preview Host Port Block (`WEB` / `API` / `DB` / `GRAPH_HTTP` / `GRAPH_BOLT`) |
|---|---|---|---|---|
| **`antigravity-factory`** | `agy` | `factory-agy-<run_id>` (or `factory-<uuid>`) | `<project>-agy-preview` | **`3100`–`3199`** (`WEB_PORT=3100`, `API_PORT=3101`, `DB_PORT=54321`, `NEO4J_HTTP_PORT=17474`, `NEO4J_BOLT_PORT=17687`) |
| **`claude-factory`** | `claude` | `factory-claude-<run_id>` (or `factory-<id>`) | `<project>-claude-preview` | **`3200`–`3299`** (`WEB_PORT=3200`, `API_PORT=3201`, `DB_PORT=54322`, `NEO4J_HTTP_PORT=27474`, `NEO4J_BOLT_PORT=27687`) |
| **`codex-factory`** | `codex` | `factory-codex-<run_id>` (or `factory-<uuid>`) | `<project>-codex-preview` | **`3300`–`3399`** (`WEB_PORT=3300`, `API_PORT=3301`, `DB_PORT=54323`, `NEO4J_HTTP_PORT=37474`, `NEO4J_BOLT_PORT=37687`) |
| **`hermes-factory`** | `hermes` | `<project>-<sha1_8>` / `factory-hermes-<run_id>` | `<project>-preview` / `<project>-hermes-preview` | **`3400`–`3499`** (`WEB_PORT=3400`, `API_PORT=3401`, `DB_PORT=54324`, `NEO4J_HTTP_PORT=47474`, `NEO4J_BOLT_PORT=47687`) |

Mandatory multi-factory Compose isolation rules:
1. **Never set `container_name` in Compose files** (Docker Compose prefixes containers with `COMPOSE_PROJECT_NAME` automatically).
2. **Zero fixed host ports during automated gates**: Gate runs either talk over the internal Compose network (`http://api:8000`, `http://web:3000`) with zero `ports:` published, or bind ephemeral `127.0.0.1::<container_port>` queried dynamically via `docker compose port`.
3. **Peer Factory Container Exemption during Teardown**: When checking before/after container snapshots at gate teardown, every factory must ignore peer ephemeral factory Compose projects (`factory-*`, `*-[0-9a-f]{8}`, `*-preview`) so concurrent runs across the 4 factories never false-fail each other's cleanup check.

## 5. `scripts/verify.sh`

- Usage: `scripts/verify.sh <milestone>` — runs every check for milestones up to and including `<milestone>` (cumulative). Milestone ids are `M0`, `M1`, …
- Exit 0 = pass, anything else = fail. No interactive prompts.
- Verbose output goes to log files (`/tmp/*.log` or bounded run logs); stdout ends with a short summary.
- Never touches resources it did not create (no host-wide prune, no other compose projects).
- Frozen at checkpoint 1 along with the tests it runs.

## 6. Freeze and holdouts

- **Freeze** happens once, at checkpoint 1, after a human approves the plan. The factory records the commit and the list of frozen files. Builders may **add** tests; they may not change or delete frozen ones.
- **Holdouts** are tests written in M0 and removed from the repository at freeze. The factory copies them in only while gating and removes them afterwards. Builders and reviewers see only failing test ids and assertion messages, never holdout source.
- **Milestone 1.5 Frozen Adversarial Tests**: Before writing implementation code, author failing happy-path and adversarial edge-case tests covering the project's 4-Part State & Edge-Case Matrix (out-of-order/duplicate inputs, concurrency/race conditions, clock/timezone boundaries, and dual-write/cross-service atomicity), then freeze them before execution.
- Holdouts are a discipline, not a secret: in permission-bypass modes an agent can read any file the user can. Say so in each repo's docs.

## 7. Roles

- **Architect** (`factory-architect`) writes the contract (M0) and probes ambiguities. Read-only during intake.
- **Builder** (`factory-builder`) implements one slice or milestone in an isolated worktree.
- **Reviewer** (`factory-reviewer`) runs in a fresh cold context, ideally from a different vendor than the builder. It enforces **Reproduce Before Fixing**: capture a failing regression test confirming each defect before patching, and ensure fixes pass the full gate.
- **Human** approves the plan (checkpoint 1) and any milestone marked `checkpoint`, and decides on protected-path changes.

## 8. Guard policy

An in-agent guard (hook) blocks honest mistakes early. It is a convenience: the gate remains the authority. `contract/guard-cases.json` lists the required decisions; every repo runs those cases against its own guard in CI.

- **Deny:** writes to `.env*` (except `.env.example`, `.env.sample`, `.env.template`, `.env.test`), private keys (`id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa`, `*.pem`, `*.key`), `.git/` internals, the factory control directory, holdout files, and frozen files. Destructive commands (`rm -rf /` or `~`, `mkfs`, fork bombs), `git push`, `--no-verify`, host-wide Docker prune, pipe-to-shell installs.
- **Ask** (deny when unattended): `git reset --hard`, `git clean -f…`, interactive rebase.
- Shell writes count as writes: redirects, `tee`, `cp`/`mv`/`ln` (including `-t`), `sed -i`, `dd of=`, `git checkout -- <path>`, through `sh -c` / `bash -c`, `$(…)` and backticks.
- Paths are normalised (`a/../.env` is `.env`). Paths outside the repo are not the guard's concern.

## 9. Records

- Run state lives **outside** the project repository, so agents cannot edit the record of their own runs.
- Each run writes one `result.json` atomically (see `contract/result.schema.json`).
- Human interventions are counted, so different factories can be compared fairly.

## 10. Benchmarks

`benchmarks/chronograph/` is the single official yardstick across all four factories, anchored on the verbatim owner-supplied handoff `benchmarks/chronograph/input/original.md` (SHA-256 `4b00410e74d5d07f500680f6d598e8e3899803207af750ea2d562cf2c062e256`):
- **Intake benchmark**: Run `factory-intake` (`factory-architect` in a fresh read-only context without evaluator files) against `input/original.md` and score against `evaluator/rubric.md` (never assume ready when blocking decisions remain).
- **End-to-end build benchmark**: Run the full factory pipeline from approved decisions through frozen tests, isolated worktrees, real Docker Compose + browser acceptance, and cold-context review; measure wall time, human interventions, and unique audit findings.

Small sample apps under `examples/` (`examples/task-tracker`, `examples/notes-app`, `examples/solo-pilot`, `examples/compose-pilot`, `examples/demo`) are fast smoke and test fixtures, not factory benchmarks.

## 11. Unified Phases, Skills, and Entry Points

All four factories expose the same 5-phase solo-developer UX and 8 canonical skills (exposed as `factory-<stage>` in Antigravity, Codex, and Hermes, and `/factory:<stage>` under Claude Code's `factory` plugin namespace):

| Phase | Canonical Skill | Claude Command | Responsibility |
|---|---|---|---|
| **All (E2E)** | `factory-pipeline` | `/factory:pipeline` | End-to-end coordinator across Phases 0–4 |
| **Phase 0** | `factory-setup` | `/factory:setup` | Project adoption, hooks, context hygiene (`/tmp/*.log`), baseline detection |
| **Phase 1** | `factory-intake` | `/factory:intake` | Route 5 entry points; read-only `factory-architect` + **4-Part State & Edge-Case Matrix** interview |
| **Phase 2** | `factory-plan` | `/factory:plan` | Lock `SPEC.md`, contracts, Compose healthchecks, **Milestone 1.5 Frozen Adversarial Tests**, slice/task freeze |
| **Phase 3** | `factory-build` | `/factory:build` | Isolated single or parallel worktree execution (`workspace: "share"` / `--worktree`) with circuit breakers |
| **Phase 4A** | `factory-verify` | `/factory:verify` | Deterministic stack gate (`NOT_RUN !== PASS`) + live browser/E2E verification |
| **Phase 4B** | `factory-review` | `/factory:review` | `audit-diff` + cold-context `factory-reviewer` + **Reproduce Before Fixing** protocol |
| **Inspect** | `factory-status` | `/factory:status` | Read-only run state, verification receipt freshness, and owner handoff summary |

Every `factory-intake` and `factory-pipeline` entrypoint handles all five developer starting points (see `docs/entry-paths.md`):
1. **New / Greenfield Project**
2. **Existing / Brownfield Repository Onboarding**
3. **Bug Fix (Reproduce-First)**
4. **Feature or Behavior Change**
5. **Large-Scale Refactor or Migration**

### Shift-Left Gate & Mandatory Spec Pushback

The factory deliberately shifts engineering rigor upfront into Phases 1 and 2 so unattended builds (`factory-build`) and deterministic gates (`factory-verify`) run without guessing:

1. **Pushback on Insufficient Requirements (`factory-intake`)**: When a developer request is vague, omits failure/boundary behavior, or leaves any applicable **4-Part State & Edge-Case Matrix** domain unresolved, `factory-intake` (`factory-architect`) **must push back** with `needs_clarification` and prioritized one-question-at-a-time inquiries (with recommended defaults) rather than guessing or proceeding to code.
2. **Refusal to Build Without Frozen Contracts & Tests (`factory-plan` → `factory-build`)**: `factory-plan` and `factory-build` refuse to start implementation until:
   - Blocking intake questions are answered in writing in a separate decision/resolution document.
   - `SPEC.md`/API/schema contracts and Docker Compose `healthcheck` definitions are locked.
   - **Milestone 1.5 Frozen Adversarial Tests** (or a failing reproduction test for bug fixes) exist and fail for the expected reason before application code is written.
   - Disjoint `allowed_paths` / slice ownership is pinned.
