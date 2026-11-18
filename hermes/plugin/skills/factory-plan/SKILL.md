---
name: factory-plan
description: "Phase 2 pre-build M0 contract & freeze gate. Pushes back if clarifications remain open, generates SPEC.md, compose.yaml, verify.sh, and Milestone 1.5 Frozen Adversarial Tests + holdouts, and locks `.factory/plan.json` via `factory freeze`."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Planning, Contracts]
    related_skills: [factory-pipeline, factory-build]
---

# factory-plan: Phase 2 Contract, Adversarial Tests & Freeze (M0)

Run M0 to lock contracts, real-stack Compose orchestration, and frozen tests before milestone implementation begins. **Pushback Gate:** Refuse Checkpoint 1 `factory freeze` if `inputs/CLARIFICATIONS.md` leaves blockers open, if M0 cross-vendor review fails, or if Milestone 1.5 adversarial tests + `tests/holdout/` self-tests are missing.

## 1. Execute M0 Contract Authoring
```bash
factory run --milestone M0 --role build --engine claude --review-engine codex --detach
```
Watch in the background (`terminal(background=true, notify=true)` running `factory wait RUN_ID --max 36000`) and end your turn—never poll in a loop.

Ensure M0 produces:
- `SPEC.md` and API/DB schemas resolving all intake decisions.
- `compose.yaml` with real services (no fixed `container_name`, no published ports during gates, no Docker socket, explicit service `healthcheck` definitions) and `e2e` Playwright test service using `data-testid` selectors.
- `scripts/verify.sh <MILESTONE>` (cumulative checks, logs redirected to `${FACTORY_ARTIFACTS:-/tmp}`).
- **Milestone 1.5 Frozen Adversarial Tests** + `scripts/holdout.sh` (`tests/holdout/`), covering happy paths and all 4 edge-case matrix failures, verified to work even when holdouts are absent in self-tests.
- `.factory/plan.json` partitioning milestones `M1..Mn` with disjoint `allowed_paths`.

## 2. Checkpoint 1 Approval & `factory freeze`
On `factory wait` notification, summarize `SPEC.md`, `.factory/plan.json` (milestones, roles, checkpoints), visible & holdout test counts, `RFI.md`, and the M0 cross-vendor review.

Ask the owner for explicit approval. Once approved:
```bash
factory note "approved plan"
factory freeze
```
For follow-up work after freeze, use `factory plan add M<n> --goal "..." --verify-as M<prev> --allowed-path <dir>/`. Proceed to `factory-build`.
