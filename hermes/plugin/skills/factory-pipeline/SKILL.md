---
name: factory-pipeline
description: "End-to-end 5-phase Hermes Factory coordinator that shifts work upfront—pushing back on insufficient specs in `factory-intake`, locking M0 contracts and Milestone 1.5 tests in `factory-plan`, then running worktree builds, external gates & browser verification, cross-vendor review, and status reporting."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Codex, Claude-Code, Orchestration, Docker]
    related_skills: [factory, factory-setup, factory-intake, factory-plan, factory-build, factory-verify, factory-review, factory-status, factory-worker]
---

# factory-pipeline: End-to-End 5-Phase Factory Coordinator

Hermes orchestrates multi-hour solo-developer software delivery across five disciplined phases. Claude Code, Codex, or Hermes itself (`factory-coder`) write code inside isolated worktrees; a different vendor reviews each milestone; and the external `factory` CLI decides pass/fail by exit codes on a real Docker Compose stack (`CONTRACT.md`).

Never edit project code yourself or decide "done" without an external gate exit 0. **Shift-Left Rule:** Push back on underspecified `inputs/HANDOFF.md` during Phase 1 (`factory-intake`) and never unlock `M1..Mn` builds until `inputs/CLARIFICATIONS.md` and Checkpoint 1 `factory freeze` (with Milestone 1.5 frozen tests and `holdouts/`) are complete.

## Phases

1. **Phase 0 (`factory-setup`)**: Run `factory doctor`, `factory setup`, and `factory init` in the repo (`--stack host --reason "..."` only if containers cannot be used); enforce `/tmp` / `${FACTORY_ARTIFACTS}` context hygiene.
2. **Phase 1 (`factory-intake`)**: Route all 5 starting points (`docs/entry-paths.md`: New Project, Existing Repo, Bug Fix [Reproduce-First], Feature/Behavior Change, Refactor/Migration). Run read-only `factory intake inputs/HANDOFF.md --engine codex`, then interview the owner via `clarify` (≤5 questions, recommended default first) probing the **4-Part State & Edge-Case Matrix**, writing `inputs/CLARIFICATIONS.md` + `factory note`.
3. **Phase 2 (`factory-plan`)**: Execute M0 (`factory run --milestone M0 --role build --engine claude --review-engine codex --detach` + background `factory wait`), locking `SPEC.md`, `compose.yaml` healthchecks, `scripts/verify.sh`, **Milestone 1.5 Frozen Adversarial Tests** & `holdouts/`, and `.factory/plan.json`. At Checkpoint 1, present summary + `RFI.md` for approval, then run `factory freeze`.
4. **Phase 3 (`factory-build`)**: Execute `M1..Mn` in isolated git worktrees via `factory pipeline` (background + notify) or Kanban `factory-worker` cards, enforcing `CONTRACT.md §8` guard rules.
5. **Phase 4 (`factory-verify` & `factory-review` -> `factory-status`)**:
   - Run `factory gate --milestone <last>` (`NOT_RUN !== PASS`) and inspect the live UI via `factory preview` + headless browser (desktop `1440x900` and mobile `390x844`).
   - Run cross-vendor cold-context `factory-review` (**Reproduce Before Fixing**) and conclude with `factory status`, reporting wall time, attempts, human interventions, and open RFIs.
