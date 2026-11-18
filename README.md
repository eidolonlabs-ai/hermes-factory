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

Part of a family of platform-native factoryes that share one [`CONTRACT.md`](CONTRACT.md):
this one (Hermes), [`codex-factory`](https://github.com/eidolonlabs-ai/codex-factory)
(Codex), and [`antigravity-factory`](https://github.com/eidolonlabs-ai/antigravity-factory)
(Antigravity).

## Why

Unattended coding agents fail in four ways: they stop early and claim success, they drown in
logs, they "fix" tests instead of code, and they block on permission prompts. This factory
answers each one outside the agent:

| Failure | What the factory does |
|---|---|
| "Done" without proof | An external gate re-runs everything; the agent's report is never evidence. `NOT_RUN` is never `PASS`. |
| Weakened tests | Tests are frozen at plan approval (hash-checked), some are **holdouts** kept out of the repo, and an in-agent guard blocks edits to frozen files. |
| Mocks instead of reality | `verify.sh` boots the whole stack in Docker Compose (database, API, web) and runs integration and Playwright E2E tests against it. |
| Permission prompts | Each run happens in a disposable git worktree; engines run with bypass inside that worktree only. Merge is fast-forward on green. |

Cross-vendor review matters: in the ChronoGraph benchmark, single-vendor audits missed bugs in
their own vendor's code that the other vendor found. See [`examples/chronograph`](examples/chronograph).

**ChronoGraph benchmark** (same 28-line handoff + 4 answers, same read-only cross-vendor audit):

| Build | Unique audit findings (high) | Human interventions |
|---|---|---|
| Antigravity | 13 (2) | 8 |
| Hermes forge (predecessor) | 7 (0) | 2 (+1) |
| **hermes-agent-factory** | **4 (1)** | 6, 3 of them factory bugs found and fixed during this first run |

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
| Skills | `factory`, `factory-worker` in your Hermes skill index | `factory setup` |
| Profiles | `factory-coder` (Hermes as a coding engine) and `factory-worker` (kanban operator), cloned from your active profile so they have your model and keys, then given their role (`SOUL.md`; the cloned one is kept as `SOUL.md.pre-factory`) | `factory setup` |
| Guard plugin | Hermes plugin `factory`, enabled in `factory-coder`: blocks writes to frozen and protected files, pushes and the like; blocks everything if the engine is missing | `factory setup` |
| Project files | AGENTS.md, compose.yaml, verify/holdout scripts, `.factory/config.json` | `factory init` in each project repo |

Your default profile's config is not modified; it only receives the two skills.

Other ways in:

- **Plugin only** (engine already installed; you manage the profile yourself):
  `hermes -p factory-coder plugins install eidolonlabs-ai/hermes-factory/hermes/plugin --enable`.
  The guard acts only in a profile named `factory-coder`; enabled anywhere else it does nothing.
- **From a checkout** (to hack on it): `git clone` then `./install.sh` for an editable install.
- **Without Hermes:** the engine alone drives `claude` and `codex`; `factory setup` skips what
  it cannot find.

Update: `uv tool upgrade hermes-agent-factory && factory setup`. Remove:
`uv tool uninstall hermes-agent-factory`, `hermes profile delete factory-coder` (and
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
factory intake inputs/HANDOFF.md --engine codex      # questions for you (read-only)
factory run --milestone M0 --role build --engine claude --review-engine codex
factory freeze                                        # after you approve .factory/plan.json
factory pipeline                                      # M1..Mn until a checkpoint / red / budget
factory status
factory preview                                       # app with published ports; --down to stop
```

For overnight runs or phone intake, use kanban mode: one card per milestone for the
`factory-worker` profile (see `hermes/plugin/skills/factory-worker`).

## What's where

| Path | |
|---|---|
| `factory/` | the CLI (Python stdlib only): gate, runner, pipeline, guard, compose policy, audit-diff |
| `template/` | files `factory init` adds to a project |
| `hermes/plugin/` | Hermes plugin: guard and verify hooks, the two skills |
| `profiles/` | the Hermes profiles `factory setup` creates |
| `contract/` | shared guard test vectors and JSON schemas |
| `CONTRACT.md` | rules shared with the sibling factoryes |
| `DESIGN.md` | architecture and decisions |
| `examples/chronograph/` | intake + build benchmarks with results |
| `tests/` | `python3 -m unittest discover -s tests` (fake engines + a real compose stack) |

## Honest limits

- Guards and holdouts protect against **mistakes**, not a malicious agent. In bypass mode an
  agent can read any file you can, including the holdout store.
- Only the code under test runs in containers; the coding agents run on your machine.
- Builders need the Docker daemon for real-stack tests, so Codex, Claude and Hermes run with
  permission bypass inside the run's disposable worktree. Claude and Hermes are guarded by
  hooks; Codex and Antigravity rely on the external gate (Codex intake stays read-only).

## License

MIT
