# Feature map: what hermes-factory adopts from its siblings

The sibling repos stay independent and platform-native (see `CONTRACT.md`). This map records
which of their capabilities this Hermes factory reimplements, and where. Rows marked
"plat/antigravity" or "plat/codex" stay in the sibling repo and are listed for reference only.
Historical source inventories: `antigravity-factory` (formerly `agy-software-factory`) @ fc268cf (Node ≥20, 39 tests passing),
`codex-factory` (formerly `codex-factory-template`) @ 9bab498 (Python 3.11+, 33 tests passing), forge (~/forge, Python).

Legend: **core** = agent-neutral `factory/` · **plat/X** = platforms/X adapter ·
**ex** = examples/ · **docs** = docs/

## From `antigravity-factory` (formerly `agy-software-factory`)

| Capability | Lands in | Notes |
|---|---|---|
| `detect` — stack/compose/component discovery (node pm, python, go, rust, monorepo dirs) | core `factory detect` | Seeds `verify.sh` and config at init |
| `verify` — hygiene + compose config + per-component lint/typecheck/test/build, receipt | core `factory check` | Keep **NOT_RUN ≠ PASS**, `requireTests`, hygiene (.env, tracked keys). Receipt moves to `~/.agent-factory`; drop "signed/cryptographic" wording (it is a digest) |
| Workspace digest | core (merge with codex candidate hash) | One hash function |
| `audit-diff` — file:line rules (secrets, eval/exec, XSS sinks, SQL interpolation, slice boundary), SARIF/markdown/GitHub summary, ignore marker | core `factory audit-diff` | Runs as a gate step after verify |
| `plan` / spec slices — allowPaths, overlap detection, globs | core `plan.json` milestones + optional `slices` | Unifies with codex `allowed_paths` |
| `land` — audit a worker worktree, copy only owned files, block on findings | core `factory land` | Used for parallel slices; milestone path stays ff-merge |
| `twin` — stateful mock HTTP server, request log, reset, HMAC webhooks, bounds | core `factory twin` | Optional tool for third-party API fakes |
| `init` — `.agents/plugins.json` link/copy, `.factory.json`, git pre-commit hook | `bootstrap-factory.sh` + plat/antigravity | Pre-commit hook becomes optional for all platforms |
| PreToolUse guard — protected paths, .env/keys, holdout, receipt forgery, shell-write parsing (redirects, cp/mv/ln/tee/sed -i/dd, `sh -c`, `$()`), force_ask on push/reset/clean, slice enforcement | core guard **policy** + per-platform wire adapters | Port the tokenizer to Python; Claude wire format recovered from fc268cf^ |
| Stop gate — receipt ok + digest matches, retry ceiling, opt-in | core policy + adapters (Claude Stop, agy Stop, Hermes pre_verify) | |
| Antigravity plugin: plugin.json, hooks.json, rules/AGENTS.md, global path | plat/antigravity | **Verified hook format** — Antigravity moves from "beta" to supported |
| Skills: spec-planner, pipeline (swarm fan-out), qa-verifier (browser subagent), security-reviewer | plat/antigravity skills | Same roles exist per platform |
| Example task-tracker (express+pg+vite, compose) | ex/task-tracker | Small fixture for compose mode |
| 39 tests (cli, hooks, 8 pipeline "apps") | tests/ ported to Python | Parity check |
| CI (Node 20/22) | CI on Python 3.11–3.13, macOS+Linux | |

## From `codex-factory` (formerly `codex-factory-template`)

| Capability | Lands in | Notes |
|---|---|---|
| `doctor` — python/OS/git clean/config/engine flag probes | core `factory doctor` | Probe every configured engine + auth |
| `intake` — read-only architect, structured questions schema, no-mutation check, docx/md/txt extraction, hashes | core `factory intake --engine X` | Engine-neutral schema; validate JSON ourselves |
| `run` — worktree, lock, attempts, scrubbed feedback, deadline, scope check, verify, review, result.json | core `factory run` | Merges with forge run loop |
| `verify` — argv checks (no shell), candidate hash before/after, per-check timeouts | core gate | Candidate-changed-during-verify is a fail |
| `status` | core | |
| models (strict task/config validation) | core | |
| process (no shell, process groups, kill descendants) | core | Better than forge's |
| workspace (locks, worktrees under git-common-dir, candidate hash) | core | Storage stays outside the worktree |
| scope/protected paths (post-hoc) | core | Add `.claude`, `.agents`, `.codex`, `platforms`, `.agent-factory` |
| review snapshot (private index commit, detached review worktree, hash unchanged) | core | Generalised: any engine reviews the snapshot |
| evidence (atomic result.json) | core | |
| Schemas (task, config, result, agent-report, intake-report) | `schemas/` | Kept + extended (milestones, roles, stack) |
| `.codex/config.toml`, agents architect/reviewer | plat/codex | |
| Skills: architect-intake, coordinate-development, implement-task, review-task, verify-task | shared prompt contracts + per-platform skill wrappers | |
| Desktop workflow (Codex app, native subagents) | plat/codex PLAYBOOK | Each platform gets a Desktop/IDE playbook |
| Docs: security, compatibility, scaling, adoption, builder-prompts, validation | docs/ | Rewritten agent-neutral |
| ChronoGraph intake benchmark: rubric, scorecard, provenance, results | ex/chronograph/intake | Plus forge build benchmark |
| 33 tests | tests/ | Parity check |

## From forge (Hermes)

| Capability | Lands in |
|---|---|
| Milestone loop, M0 contract, freeze, cross-vendor review, `verify_as` follow-ups, intervention log | core |
| Claude headless fixes (strict MCP, empty config), Codex flags | core engine adapters |
| Kanban mode, forge-worker skill, profiles, notifications | plat/hermes |
| Prompts (m0_build, m0_review, build, review incl. visual pass) | core prompts |
| ChronoGraph build benchmark + audit report | ex/chronograph/build |

## Decisions (see DESIGN.md)
1. Core language → Python stdlib (Hermes is Python). Useful Node logic is ported, not wrapped.
2. Agent permissions → sandboxed where the engine supports it (Codex `workspace-write`, no bypass);
   bypass only inside factory worktrees for engines without a sandbox.
3. Done → gate + (ff-merge | PR | stop for human), set per project. Codex template's
   "ready_for_human_review" is the `merge: human` mode.
4. Tests-protection → three layers: pre-tool guard (prevent), frozen hash + scope check (detect), holdouts (hide).
