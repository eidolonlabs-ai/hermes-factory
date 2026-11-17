---
name: harness
description: "Use for unattended milestone builds. Drive the harness CLI."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Codex, Claude-Code, Orchestration, Docker]
    related_skills: [harness-worker, codex, claude-code]
---

# harness: unattended milestone builds, Hermes orchestrates

Hermes turns a spec into a working app over hours, milestone by milestone. Claude Code,
Codex or Hermes itself (profile `harness-coder`) write the code; a different vendor reviews
each milestone; the `harness` CLI decides pass/fail from exit codes on a real Docker Compose
stack. You (Hermes) talk to the user, run the CLI, watch, and report. You never edit project
code yourself and never decide "done" yourself. Rules: `CONTRACT.md`; design: `DESIGN.md`.

## When to Use
- "Build this app/feature from this spec, let it run, ping me at milestones"
- "Run the harness / pipeline / next milestone", "is M3 green?", "add a follow-up milestone"
- A kanban card or cron job that should start or continue a harness project

## Prerequisites
- `harness doctor` is ok: Python 3.11+, git, Docker daemon + Compose v2, and at least the
  engines named in `.harness/config.json` (`claude auth status`, `codex login status`).
- Installed via the repo's `install.sh` (puts `harness` on PATH, profiles, this skill).

## Procedure
1. **Preflight** (`terminal`): `harness doctor`. Fix engine logins before anything burns.
2. **Project**: `cd REPO && git init -b main` if needed; `harness init` (copies the template:
   AGENTS.md, compose.yaml, scripts, inputs/). Put the user's spec in `inputs/HANDOFF.md`.
   Commit. Projects that cannot run in Linux containers: `harness init --stack host --reason "..."`.
3. **Intake**: `harness intake inputs/HANDOFF.md --engine codex` (read-only architect).
   Ask the user the blocking questions with `clarify` (one form, ≤5 questions per call, your
   recommended answer first). Write answers to `inputs/CLARIFICATIONS.md`, host constraints to
   `inputs/ENVIRONMENT.md`. Commit. `harness note "intake answers"`.
4. **M0 contract**: `harness run --milestone M0 --role build --engine claude --review-engine codex --detach`,
   then a background watcher: `terminal(background=true, notify=true)` running
   `harness wait RUN_ID --max 36000`. End your turn.
5. **Checkpoint 1** (on notify): summarize SPEC.md, `.harness/plan.json` (milestones, roles,
   checkpoints), test and holdout counts, `RFI.md`, the M0 review. Ask for approval. On approval:
   `harness note "approved plan"` then `harness freeze`.
6. **Milestones**: start `harness pipeline` as a background process with notify
   (`terminal(background=true, notify=true)`). It stops at checkpoints, a red gate after all
   attempts, `needs_human` (protected path changed) or budget. End your turn.
7. **On each stop**: read the summary JSON and `harness status`. Report to the user in a few
   lines (what passed, what stopped, why). For a red gate show the failing check and the log
   tail path, not whole logs. Continue with `harness pipeline` when the user agrees; log every
   human decision with `harness note`.
8. **Final**: run `harness gate --milestone <last>` yourself (background + notify);
   `harness preview` and check the UI with the browser tools (desktop 1440x900 and mobile
   390x844); `harness preview --down` when the user is done. Optionally a cross-vendor audit:
   `templates/audit/` + `references/benchmarking.md`. Report wall time, attempts,
   interventions (user decisions vs harness bugs), and open RFIs.
9. **Follow-ups** (plan is frozen): `harness plan add M6 --goal "..." --verify-as M5 --allowed-path api/`
   then `harness pipeline --next`.

## Kanban mode
For overnight runs, phone intake, or several projects: one card per milestone assigned to
profile `harness-worker` with skill `harness-worker`; the card body ends with a fenced `harness`
block `{"repo": "/abs/path", "milestone": "M3"}`. Chain cards with parents so they run in order.

## Pitfalls
- Never run `codex`/`claude` directly for project work, never edit frozen files, never
  `git push`. The CLI is the only writer of run state (`~/.hermes/harness/`).
- A long `harness wait` or `pipeline` exceeds the 600 s foreground cap: always background it
  with notify, then end the turn. Do not poll in a loop.
- A wrong frozen test can only be fixed deliberately: tell the user, get approval, fix it on
  main, `harness freeze --force`, `harness note`.
- `stack.type: host` projects report "not isolated" in every gate; say so in reports.
- Expired Claude/Codex logins fail every attempt instantly; `harness doctor` first.
- A run that goes red for a reason the builder cannot fix (harness bug, wrong frozen file):
  stop the pipeline, fix the cause, then resume with `harness run --milestone M ...
  --feedback-file F` telling the engine to `git merge` the red run's branch first, so no
  finished work is redone. Log it with `harness note`.
- If `browser_exec` screenshots time out, use headless Chrome
  (`--headless=new --window-size=1440,900 --virtual-time-budget=8000 --screenshot=out.png URL`).
- Benchmarks and audits: follow `references/benchmarking.md` exactly (same inputs, strip
  process artifacts like `docs/reviews` and `RFI.md` from every audited clone).

## Verification
`harness gate --milestone <last>` exits 0 and its JSON shows every check PASS (holdout/audit
may be NOT_RUN only if disabled), `compose-teardown` PASS, and `harness status` shows all
milestones merged.
