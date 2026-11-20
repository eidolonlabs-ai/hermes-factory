# Hermes Factory

Hand [Hermes Agent](https://hermes-agent.nousresearch.com) a spec, answer its questions,
approve a plan, and let it build your app for hours, milestone by milestone, without clicking
"approve". Hermes orchestrates; **Claude Code**, **Codex** or **Hermes itself** write the code;
a **different vendor** reviews every milestone; and whether a milestone is done is decided by
exit codes on a **real Docker Compose stack**, never by an agent saying "done".

```
you ──spec──► Hermes ── intake questions ──► you
                 │
                 ├─ M0  architect writes SPEC, compose.yaml, verify.sh, tests, holdouts, plan
                 ├─ ✋  you approve the plan → freeze
                 └─ M1..Mn, each in its own git worktree:
                      builder (codex | claude | hermes) → GATE → cross-vendor review → GATE → merge
                      GATE = scope · frozen tests · hygiene · compose policy ·
                             verify.sh on the live stack · holdouts · diff audit · candidate hash
```

Part of a family of platform-native factories that share one [`CONTRACT.md`](CONTRACT.md):
this one (Hermes), [`antigravity-factory`](https://github.com/eidolonlabs-ai/antigravity-factory)
(Antigravity), [`claude-factory`](https://github.com/eidolonlabs-ai/claude-factory)
(Claude Code), and [`codex-factory`](https://github.com/eidolonlabs-ai/codex-factory)
(Codex). See [5 entry points](docs/entry-paths.md) and the unified skills (`factory-pipeline`,
`factory-setup`, `factory-intake`, `factory-plan`, `factory-build`, `factory-verify`,
`factory-review`, `factory-status`).

## Why Prompts & Skills Alone Fail vs. This Software Factory

Prompts and `SKILL.md` guides alone are **probabilistic**—over multi-hour builds, coding agents stop early and claim "done", drown in verbose test logs, weaken failing tests to turn builds green, or stall on permission prompts. **Hermes Factory** pairs multi-vendor orchestration (Claude Code, Codex, Hermes) with **deterministic runtime physics** outside the agent's session (`CONTRACT.md`):

| Layer | Nature | What It Provides Here |
|---|---|---|
| **1. Prompt Engineering** | Probabilistic (Single Turn) | 8 unified stage skills (`factory-pipeline` through `factory-status`) + `factory` / `factory-worker` kanban operator |
| **2. Context Engineering** | Probabilistic (Session State) | `template/AGENTS.md`, `SPEC.md`, `inputs/{HANDOFF,CLARIFICATIONS,ENVIRONMENT}.md`, and log-to-file tails |
| **3. Factory / Harness Engineering** | Deterministic (Runtime Physics) | External `factory gate` exit codes on real Docker Compose stacks (`NOT_RUN !== PASS`), frozen file hashes, **holdout** tests stored outside the repo, in-agent `factory-hook` guards, disposable git worktrees, and cross-vendor cold-context reviews |

| Failure | Why Prompts/Skills Alone Fail | How Hermes Factory Solves It Deterministically |
|---|---|---|
| **"Done" without proof** | Agent reports "all tests pass" without running real services | An external gate re-runs everything (`scripts/verify.sh`); the agent's report is never evidence. `NOT_RUN` is never `PASS`. |
| **Context window rot** | Long Docker builds and test logs push out requirements | Outputs go to log files under `${FACTORY_ARTIFACTS:-/tmp}`; runners pass only bounded tails across attempts and spawn fresh worktrees per milestone. |
| **Weakened tests** | Builders edit failing assertions or mock out databases | Tests are frozen at Checkpoint 1 (hash-checked), **holdouts** live outside the repo, an in-agent guard blocks writes to frozen files, and `verify.sh` boots a real Compose stack (Postgres, Neo4j, API, web, Playwright). |
| **Permission prompts** | Long unattended runs block on interactive confirmations | Each milestone runs in a disposable git worktree; engines run with bypass inside that worktree only, guarded by `factory-hook`. Fast-forward merge happens only on green. |

## Shift-Left Engineering: Built-In Spec Pushback

Multi-hour unattended runs (`factory pipeline`) only finish cleanly when ambiguity is resolved **upfront**:

- **Mandatory Intake Pushback (`factory-intake`)**: If `inputs/HANDOFF.md` is vague, omits error handling, or leaves any **4-Part State & Edge-Case Matrix** domain undefined (out-of-order/duplicates, concurrency/row locks & `AbortController`, UTC/`as_of` clock bounds, dual-write atomicity), read-only `factory intake` **pushes back** (`needs_clarification`), and Hermes interviews you via `clarify` (recording answers in `inputs/CLARIFICATIONS.md`) before M0 starts.
- **Checkpoint 1 Contract & Test Freeze (`factory-plan` → `factory-build`)**: M0 authors `SPEC.md`, `compose.yaml` healthchecks, `scripts/verify.sh`, **Milestone 1.5 Frozen Adversarial Tests**, and `tests/holdout/`—all audited by a cross-vendor reviewer—before `factory freeze` unlocks `M1..Mn` builds.

## How to Choose Your Entry Point & Stage

Start with **`factory-pipeline`** (or **`factory`**) for end-to-end orchestration. Invoke an individual stage skill directly only when its upstream prerequisites already exist (see [5 entry points](docs/entry-paths.md)):

| Entry Point | Minimum Inputs | When `factory-intake` Pushes Back |
|---|---|---|
| **1. New / Greenfield App** | Users, core journeys, stack constraints, `inputs/HANDOFF.md` | Undefined schemas/endpoints or unresolved 4-Part Matrix edge cases |
| **2. Existing / Brownfield Repo** | Repo path, goal, conventions, test commands, known failures | Missing `scripts/verify.sh` checks or unstated stack constraints |
| **3. Bug Fix (Reproduce-First)** | Expected vs. actual behavior, repro steps, logs | Missing reproduction steps or skipping a failing test (`factory plan add`) |
| **4. Feature / Behavior Change** | Desired behavior, exemplar files, compatibility constraints | Unclear schema/API deltas or unmapped milestone acceptance |
| **5. Refactor / Migration** | Target modules, invariants, verification scripts | Missing baseline verification or overlapping `allowed_paths` |

| Phase | Skill | When to Invoke Directly |
|---|---|---|
| **All (E2E)** | `factory-pipeline` (or `factory`) | Guided Phases 0–4 unattended orchestration with checkpoints and notifications |
| **Phase 0** | `factory-setup` | Checking auth/Docker (`factory doctor`), installing profiles (`factory setup`), or `factory init` |
| **Phase 1** | `factory-intake` | Auditing a raw spec (`benchmarks/chronograph/input/original.md`) via read-only `factory intake` + `clarify` |
| **Phase 2** | `factory-plan` | Clarifications recorded; ready for M0 contracts, Milestone 1.5 + holdout tests, Checkpoint 1, and `factory freeze` |
| **Phase 3** | `factory-build` | Plan frozen; running `factory pipeline`, `factory run --milestone <M>`, or kanban `factory-worker` |
| **Phase 4A** | `factory-verify` | Running external `factory gate` (`NOT_RUN !== PASS`) + `factory preview` browser checks (`1440x900`, `390x844`) |
| **Phase 4B** | `factory-review` | Cross-vendor cold-context review (`--review-engine cross`, **Reproduce Before Fixing**) or `templates/audit/` |
| **Inspect** | `factory-status` | Checking `factory status`, `result.json`, `factory note` interventions, and `RFI.md` |

Cross-vendor review matters: in the ChronoGraph benchmark, single-vendor audits missed bugs in
their own vendor's code that the other vendor found. See [`examples/chronograph`](examples/chronograph).

**ChronoGraph benchmark** (same 28-line handoff + 4 answers, same read-only cross-vendor audit):

| Build | Unique audit findings (high) | Human interventions |
|---|---|---|
| Antigravity | 13 (2) | 8 |
| Hermes forge (predecessor) | 7 (0) | 2 (+1) |
| **hermes-factory** | **4 (1)** | 6, 3 of them factory bugs found and fixed during this first run |

## Requirements

- macOS or Linux, Python 3.11+, git
- Docker with Compose v2 (projects that cannot run in Linux containers can opt out with a
  written reason; their gates say "not isolated")
- Hermes Agent, plus at least one coding engine logged in: `claude`, `codex`
  (`agy` optional)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/eidolonlabs-ai/hermes-factory/main/install.sh | bash
factory doctor
```

That installs the engine with [uv](https://docs.astral.sh/uv/) (or pipx) and runs
`factory setup`. The same thing by hand:

```bash
uv tool install git+https://github.com/eidolonlabs-ai/hermes-factory
factory setup            # --dry-run to preview
```

| Piece | What you get | Installed by |
|---|---|---|
| Engine | `factory` and `factory-hook` on PATH (Python stdlib only) | `uv tool install` / `pipx install` |
| Skills | `factory-pipeline`, `factory-setup`, `factory-intake`, `factory-plan`, `factory-build`, `factory-verify`, `factory-review`, `factory-status`, plus `factory` and `factory-worker` in your Hermes skill index | `factory setup` |
| Profiles | `factory-coder` (Hermes as a coding engine) and `factory-worker` (kanban operator), cloned from your active profile so they have your model and keys, then given their role (`SOUL.md`; the cloned one is kept as `SOUL.md.pre-factory`) | `factory setup` |
| Guard plugin | Hermes plugin `factory`, enabled in `factory-coder`: blocks writes to frozen and protected files, pushes and the like; blocks everything if the engine is missing | `factory setup` |
| Project files | AGENTS.md, compose.yaml, verify/holdout scripts, `.factory/config.json` | `factory init` in each project repo |

Your default profile's config is not modified; it only receives the factory skills.

Other ways in:

- **Plugin only** (engine already installed; you manage the profile yourself):
  `hermes -p factory-coder plugins install eidolonlabs-ai/hermes-factory/hermes/plugin --enable`.
  The guard acts only in a profile named `factory-coder`; enabled anywhere else it does nothing.
- **From a checkout** (to hack on it): `git clone` then `./install.sh` for an editable install.
- **Without Hermes:** the engine alone drives `claude` and `codex`; `factory setup` skips what
  it cannot find.

Update: `uv tool upgrade hermes-factory && factory setup`. Remove:
`uv tool uninstall hermes-factory`, `hermes profile delete factory-coder` (and
`factory-worker`), and delete `~/.hermes/skills/software-factory/factory*`.

## Use

In a Hermes chat:

> Build the app in `inputs/HANDOFF.md` in `~/code/myapp` with the factory. Ping me at checkpoints.

Hermes follows the `factory` skill: `factory init` (adds AGENTS.md, compose.yaml, verify.sh
skeletons), read-only intake, your answers, M0, your plan approval, then `factory pipeline` in
the background. It messages you at checkpoints, red gates and the end.

Or drive it yourself:

```bash
cd ~/code/myapp && git init -b main && factory init
$EDITOR inputs/HANDOFF.md
factory intake inputs/HANDOFF.md                      # read-only; uses roles.architect
factory run --milestone M0 --role build --review-engine configured
factory freeze                                        # after you approve .factory/plan.json
factory pipeline                                      # M1..Mn until a checkpoint / red / budget
factory gate --final                                 # audit the whole build since freeze
factory status
factory preview                                       # app with published ports; --down to stop
```

To use Claude Code for building and Hermes for review, set these keys in
`.factory/config.json` before intake and freeze:

```json
{
  "roles": {"architect": "claude", "backend": "claude", "ui": "claude", "review": "cross"},
  "cross": {"claude": "hermes", "hermes": "claude"}
}
```

An explicit `cross` map replaces the legacy mapping; a builder without an entry has no
cross reviewer. Explicit `builder` and `reviewer` values in the plan still override roles.
Intake requires a read-only engine (Claude Code or Codex). Installed engines are not
assumed to be subscribed or selected.

`factory status` reports observed token counts and `cost_usd` as an API-rate estimate,
not subscription spend. The project cap uses that estimate for build and review attempts.
`usage_incomplete_attempts` flags missing cost or token data; historic runs are not backfilled.
The cap is best-effort: unreported cost cannot be enforced against it. Attempt and
wall-clock limits still apply, including on older Hermes releases without usage reports.

For overnight runs or phone intake, use kanban mode: one card per milestone for the
`factory-worker` profile (see `hermes/plugin/skills/factory-worker`).

## What's where

| Path | |
|---|---|
| `factory/` | the CLI (Python stdlib only): gate, runner, pipeline, guard, compose policy, audit-diff |
| `template/` | files `factory init` adds to a project |
| `hermes/plugin/` | Hermes plugin (`plugin.yaml`, `__init__.py`, `README.md`): guard/verify hooks + the 8 unified `factory-*` skills plus `factory` and `factory-worker` |
| `profiles/` | the Hermes profiles `factory setup` creates |
| `contract/` | shared guard test vectors and JSON schemas |
| `CONTRACT.md` | rules shared with the sibling factories |
| `DESIGN.md` | architecture and decisions |
| `docs/entry-paths.md` | 5 developer entry points & 5-phase workflow |
| `benchmarks/chronograph/` | official intake & build benchmark (`original.md`) |
| `examples/chronograph/` | recorded intake + build benchmark runs & audits |
| `tests/` | `python3 -m unittest discover -s tests` (fake engines + a real compose stack) |

## Plugin Packaging, Validation & Marketplace Distribution

`hermes/plugin/` is packaged directly inside Python wheels (`factory/_data/plugin` via `pyproject.toml`) **and** structured as a standalone `hermes plugins install` bundle with zero duplicated helper scripts inside each skill subfolder (skills invoke the shared `factory` / `factory-hook` CLI on `PATH`):

- **Validate the plugin locally** before pushing or catalog submission:
  ```bash
  hermes plugins validate ./hermes/plugin
  hermes plugins doctor ./hermes/plugin
  ```
- **Install from GitHub / catalog**:
  - Full engine + skills + profiles (recommended): `curl -fsSL https://raw.githubusercontent.com/eidolonlabs-ai/hermes-factory/main/install.sh | bash` (or `uv tool install git+https://github.com/eidolonlabs-ai/hermes-factory && factory setup`).
  - Plugin subdirectory directly: `hermes -p factory-coder plugins install eidolonlabs-ai/hermes-factory/hermes/plugin --enable` (when `factory` / `factory-hook` are already on `PATH`).
- **Implementation parallelism & slices**: Instead of concurrent same-repo file slices, `hermes-factory` isolates sequential milestones in disposable worktrees while specializing roles across engines (`"roles": {"architect": "claude", "backend": "codex", "ui": "claude", "review": "cross"}`), supports multi-card / multi-repo concurrency via `factory-worker` Kanban cards, and fans out read-only audits across engines (`factory audit --engines claude,codex`).

## Honest limits

- Guards and holdouts protect against **mistakes**, not a malicious agent. In bypass mode an
  agent can read any file you can, including the holdout store.
- Only the code under test runs in containers; the coding agents run on your machine.
- Builders need the Docker daemon for real-stack tests, so Codex, Claude and Hermes run with
  permission bypass inside the run's disposable worktree. Claude and Hermes are guarded by
  hooks; Codex and Antigravity rely on the external gate (Codex intake stays read-only).

## License

MIT
