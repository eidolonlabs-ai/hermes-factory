---
name: factory-build
description: "Phase 3 worktree-isolated milestone execution (`factory pipeline`, `factory run`, or kanban `factory-worker`). Verifies a frozen plan and Milestone 1.5 tests exist first, routing back to `factory-intake` / `factory-plan` if missing."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Execution, Worktrees]
    related_skills: [factory-pipeline, factory-verify, factory-worker]
---

# factory-build: Phase 3 Isolated Milestone Execution

Run frozen milestones inside disposable git worktrees governed by the `factory-coder` guard plugin and external gates.

> **Pre-Flight Freeze Check (Pushback Gate):** Never start `M1..Mn` coding unless `inputs/CLARIFICATIONS.md` is committed, M0 passed cross-vendor review, and `factory freeze` locked `.factory/plan.json` and frozen tests. If requirements or frozen tests are missing, stop and route back to `factory-intake` / `factory-plan`.

## Execution Modes

1. **Autonomous Pipeline (`M1..Mn`)**:
   Start `factory pipeline` as a background process with notify (`terminal(background=true, notify=true)`) and end your turn. It stops cleanly at checkpoints, exhausted attempt budgets, `needs_human` (protected path changes), or budget limits.
2. **Single Milestone Run**:
   ```bash
   factory run --milestone <M> --role build --engine <claude|codex|hermes> --review-engine cross --detach
   ```
   Follow with background `factory wait RUN_ID --max 36000`.
3. **Kanban Card Mode**:
   Delegate cards to profile `factory-worker` with skill `factory-worker` (`{"repo": "/abs/path", "milestone": "M3"}`).

## Operational & Recovery Rules
- Never run `codex` or `claude` directly for project edits, never edit frozen files (`factory freeze --force` requires explicit human approval), and never `git push`.
- If a run stops red due to a factory/contract bug rather than a builder bug, fix the root cause after owner approval, then resume with `factory run --milestone M ... --feedback-file F` instructing the builder to `git merge` the red branch first so completed work is preserved. Log every human decision with `factory note`.
Proceed to `factory-verify`.
