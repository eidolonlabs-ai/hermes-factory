---
name: factory-review
description: "Phase 4B cross-vendor cold-context review & audit (`--review-engine cross`, `audit-diff`, `templates/audit/`), enforcing Reproduce Before Fixing."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Review, Security]
    related_skills: [factory-pipeline, factory-status]
---

# factory-review: Phase 4B Cross-Vendor Cold-Context Review

Pair automated diff scanning with a fresh, cross-vendor reviewer (`codex` reviewing `claude` or `claude` reviewing `codex`) so author-vendor blind spots are caught cleanly.

## 1. Per-Milestone & Final Cross-Vendor Review
- Ensure every milestone uses `--review-engine cross` (or explicit opposite vendor) and passes `audit-diff` (secrets, `eval`, SQL interpolation, XSS sinks).
- Inspect `git diff` in a cold context covering the **4-Part State & Edge-Case Matrix**:
  - DB row locks (`SELECT FOR UPDATE`) and transaction isolation.
  - Stale graph/relation cleanup prior to `MERGE`/upsert and dual-write consistency.
  - UTC ISO-8601 timestamps and explicit `as_of` historical cursors vs `now()`.
  - UI `AbortController` + monotonic counters + unique `data-testid` selectors.

## 2. Enforce "Reproduce Before Fixing"
For every defect discovered in review:
1. Write a failing regression test reproducing the exact bug first.
2. Confirm failure in the test suite.
3. Apply the minimal fix inside the milestone worktree.
4. Re-run `factory gate --milestone <id> --worktree <path> --base <starting-sha>` before merging.

## 3. Optional Full-Build Cross-Vendor Audit
Follow `../factory/references/benchmarking.md` and `../factory/templates/audit/` (always stripping process artifacts like `docs/reviews/`, `RFI.md`, `.factory/`, and `inputs/` before cross-factory benchmark audits). Proceed to `factory-status`.
