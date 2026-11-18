# Start a development task (`hermes-factory`)

Install the engine (`uv tool install git+https://github.com/eidolonlabs-ai/hermes-factory && factory setup`), initialize your project (`factory init`), and invoke `factory-pipeline` (or drive individual `factory-*` stage skills) in Hermes Chat, CLI, or Kanban mode (`factory-worker`).

> **Shift-Left Habit:** Multi-hour unattended milestone loops (`factory pipeline`) and cross-vendor reviews only work reliably when requirements, edge cases, contracts, and Milestone 1.5 adversarial tests are locked *before* M1 begins. If `inputs/HANDOFF.md` is vague, `factory-intake` will push back (`needs_clarification`) via `clarify` rather than guessing.

## 1. Choose Your Entry Point (Minimum Inputs & Pushback Triggers)

| Starting point | Minimum inputs required | When the factory pushes back (`needs_clarification`) | First milestone |
| --- | --- | --- | --- |
| **1. New / Greenfield App** | Intended users, core journeys, constraints, and `inputs/HANDOFF.md` | Vague 1-liners, undefined schemas/endpoints, or unresolved **4-Part State & Edge-Case Matrix** domains | Run read-only `factory intake` + `clarify` on the 4-Part Matrix, record answers in `inputs/CLARIFICATIONS.md`, execute M0 (`SPEC.md`, `compose.yaml`, `scripts/verify.sh`, **Milestone 1.5 Frozen Adversarial Tests**, `holdouts/`), and `factory freeze` at Checkpoint 1. |
| **2. Existing / Brownfield Repo** | Repo path, concrete goal, conventions, test commands, and known failures | Missing Compose/host stack config or absent `scripts/verify.sh` test assertions | Run `factory doctor` + `factory init`, wrap existing build/test checks in `scripts/verify.sh`, establish baseline `factory gate`, and plan scoped milestones `M1..Mn`. |
| **3. Bug Fix (Reproduce-First)** | Expected vs. actual behavior, reproduction steps, and error logs | Missing reproduction steps or request to skip adding a failing regression test | Author a failing regression test first (**Reproduce Before Fixing**) as a frozen or follow-up milestone (`factory plan add`), confirm failure, implement in an isolated worktree, and rerun `factory gate`. |
| **4. Feature / Behavior Change** | Desired behavior, exemplar files, compatibility constraints, and error handling | Unspecified API/schema deltas or unmapped milestone acceptance criteria | Define milestone `allowed_paths`, contract deltas, and cumulative checks in `.factory/plan.json` (or `factory plan add` on a frozen plan) before executing `factory pipeline`. |
| **5. Large-Scale Refactor / Migration** | Target modules, invariant guarantees, and verification scripts | Missing baseline verification or overlapping milestone ownership | Freeze baseline verification + holdout tests first, partition disjoint milestones `M1..Mn` with `allowed_paths`, and run autonomously via `factory pipeline` or Kanban `factory-worker` cards. |

## 2. How to Choose Which Skill / Stage to Invoke

Start with **`factory-pipeline`** (or **`factory`** for quick CLI-driven unattended builds) whenever you want guided orchestration. Invoke an individual stage skill directly only when its upstream artifacts already exist:

| Skill | Invoke directly when… | What happens if prerequisites are missing (Pushback) |
| --- | --- | --- |
| **`factory-pipeline`** | Default entry point for full end-to-end builds across Phases 0–4 | Refuses to advance from Phase 1/2 to Phase 3 until `inputs/CLARIFICATIONS.md` and Checkpoint 1 `factory freeze` are complete |
| **`factory-setup`** | Checking logins/Docker (`factory doctor`), installing profiles (`factory setup`), or initializing a repo (`factory init`) | Stops early on missing engine auth or missing container runtime (`--stack host --reason` required for non-Linux opt-out) |
| **`factory-intake`** | Auditing a new spec (`inputs/HANDOFF.md` or `benchmarks/chronograph/input/original.md`) before M0 | **Pushes back** (`needs_clarification`) via read-only `factory intake` + `clarify` covering the 4-Part Matrix |
| **`factory-plan`** | Clarifications are committed and you are ready to generate M0 (`SPEC.md`, `compose.yaml`, Milestone 1.5 tests + `holdouts/`, `.factory/plan.json`) and freeze at Checkpoint 1 | **Blocks freeze** until M0 self-tests pass even with `tests/holdout/` absent, cross-vendor M0 review passes, and the human approves |
| **`factory-build`** | Plan is frozen and ready to run `M1..Mn` via `factory pipeline`, `factory run`, or `factory-worker` kanban cards | **Refuses execution** without a frozen plan (`factory freeze`); stops red and notifies on scope/budget exhaustion |
| **`factory-verify`** | Running external `factory gate --milestone <M>` and `factory preview` browser checks (`1440x900` / `390x844`) | Fails closed on `NOT_RUN`, frozen edits, holdout failures, or unsafe Compose configs |
| **`factory-review`** | Running cross-vendor cold-context review (`--review-engine cross`) or full build audit (`templates/audit/`) | Enforces **Reproduce Before Fixing** (new failing test before minimal fix) and strips process artifacts in cross-factory audits |
| **`factory-status`** | Checking `~/.hermes/factory/` state (`factory status`), `result.json`, `factory note` interventions, and `RFI.md` | Reports exact gate results, attempts, and open blockers without claiming unverified completion |
