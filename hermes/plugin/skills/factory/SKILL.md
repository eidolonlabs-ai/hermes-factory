---
name: factory
description: "Use for unattended milestone builds. Drive the factory CLI."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Codex, Claude-Code, Orchestration, Docker]
    related_skills: [factory-pipeline, factory-setup, factory-intake, factory-plan, factory-build, factory-verify, factory-review, factory-status, factory-worker, codex, claude-code]
---

# factory: unattended milestone builds, Hermes orchestrates

Hermes turns a spec into a working app over hours, milestone by milestone. Claude Code,
Codex or Hermes itself (profile `factory-coder`) write the code; a different vendor reviews
each milestone; the `factory` CLI decides pass/fail from exit codes on a real Docker Compose
stack. You (Hermes) talk to the user, run the CLI, watch, and report. You never edit project
code yourself and never decide "done" yourself. Rules: `CONTRACT.md`; design: `DESIGN.md`.

*(For the unified 5-phase skill family shared across Antigravity, Claude Code, Codex, and Hermes, see `factory-pipeline` and stage skills `factory-setup`, `factory-intake`, `factory-plan`, `factory-build`, `factory-verify`, `factory-review`, and `factory-status`.)*

## When to Use
- "Build this app/feature from this spec, let it run, ping me at milestones"
- "Run the factory / pipeline / next milestone", "is M3 green?", "add a follow-up milestone"
- A kanban card or cron job that should start or continue a factory project

## Prerequisites
- `factory doctor` is ok: Python 3.11+, git, Docker daemon + Compose v2, and at least the
  engines named in `.factory/config.json` (`claude auth status`, `codex login status`).
- Engine installed (`factory --version`); if missing: `uv tool install
  git+https://github.com/eidolonlabs-ai/hermes-factory` then `factory setup` (skills,
  profiles `factory-coder` / `factory-worker`, guard plugin). Re-run `factory setup` after upgrades.

## Procedure
1. **Preflight** (`terminal`): `factory doctor`. Fix engine logins before anything burns.
2. **Project**: `cd REPO && git init -b main` if needed; `factory init` (copies the template:
   AGENTS.md, compose.yaml, scripts, inputs/). Put the user's spec in `inputs/HANDOFF.md`.
   Commit. Projects that cannot run in Linux containers: `factory init --stack host --reason "..."`.
3. **Intake (Shift-Left Pushback)**: `factory intake inputs/HANDOFF.md` (read-only architect).
   Audit `inputs/HANDOFF.md` for sufficiency; actively push back (`needs_clarification`) when requirements, failure modes, or the 4-Part State & Edge-Case Matrix are incomplete—never wave thin prompts into M0. Ask the user the blocking questions with `clarify` (one form, ≤5 questions per call, your recommended answer first). Write answers to `inputs/CLARIFICATIONS.md`, host constraints to `inputs/ENVIRONMENT.md`. Commit. `factory note "intake answers"`.
4. **M0 contract**: `factory run --milestone M0 --role build --review-engine configured --detach`,
   then a background watcher: `terminal(background=true, notify=true)` running
   `factory wait RUN_ID --max 36000`. End your turn.
5. **Checkpoint 1** (on notify): summarize SPEC.md, `.factory/plan.json` (milestones, roles,
   checkpoints), test and holdout counts, `RFI.md`, the M0 review. Ask for approval. On approval:
   `factory note "approved plan"` then `factory freeze`.
6. **Milestones**: start `factory pipeline` as a background process with notify
   (`terminal(background=true, notify=true)`). It stops at checkpoints, a red gate after all
   attempts, `needs_human` (protected path changed) or budget. End your turn.
7. **On each stop**: read the summary JSON and `factory status`. Report to the user in a few
   lines (what passed, what stopped, why). For a red gate show the failing check and the log
   tail path, not whole logs. Continue with `factory pipeline` when the user agrees; log every
   human decision with `factory note`.
8. **Final**: run `factory gate --final` yourself (background + notify);
   `factory preview` and check the UI with the browser tools (desktop 1440x900 and mobile
   390x844); `factory preview --down` when the user is done. Optionally a cross-vendor audit:
   `templates/audit/` + `references/benchmarking.md`. Report wall time, attempts,
   interventions (user decisions vs factory bugs), and open RFIs.
9. **Follow-ups** (plan is frozen): `factory plan add M6 --goal "..." --verify-as M5 --allowed-path api/`
   then `factory pipeline --next`.

## Kanban mode
For overnight runs, phone intake, or several projects: one card per milestone assigned to
profile `factory-worker` with skill `factory-worker`; the card body ends with a fenced `factory`
block `{"repo": "/abs/path", "milestone": "M3"}`. Chain cards with parents so they run in order.

## Pitfalls
- Never run `codex`/`claude` directly for project work, never edit frozen files, never
  `git push`. The CLI is the only writer of run state (`~/.hermes/factory/`).
- A long `factory wait` or `pipeline` exceeds the 600 s foreground cap: always background it
  with notify, then end the turn. Do not poll in a loop.
- A wrong frozen test can only be fixed deliberately: tell the user, get approval, fix it on
  main, `factory freeze --force`, `factory note`.
- `stack.type: host` projects report "not isolated" in every gate; say so in reports.
- Expired Claude/Codex logins fail every attempt instantly; `factory doctor` first.
- A run that goes red for a reason the builder cannot fix (factory bug, wrong frozen file):
  stop the pipeline, fix the cause, then resume with `factory run --milestone M ...
  --feedback-file F` telling the engine to `git merge` the red run's branch first, so no
  finished work is redone. Log it with `factory note`.
- If `browser_exec` screenshots time out, use headless Chrome
  (`--headless=new --window-size=1440,900 --virtual-time-budget=8000 --screenshot=out.png URL`).
- Benchmarks and audits: follow `references/benchmarking.md` exactly (same inputs, strip
  process artifacts like `docs/reviews` and `RFI.md` from every audited clone).

## Verification
`factory gate --final` exits 0 and its JSON shows every check PASS (holdout/audit
may be NOT_RUN only if disabled), `compose-teardown` PASS, and `factory status` shows all
milestones merged.
