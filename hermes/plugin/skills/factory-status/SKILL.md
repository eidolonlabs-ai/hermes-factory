---
name: factory-status
description: "Inspect Hermes Factory milestone status, run `result.json`, human interventions, and open RFIs via `factory status`."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Status, Reporting]
    related_skills: [factory-pipeline, factory-verify]
---

# factory-status: Inspect Factory State & Report

Check durable run state stored outside the project repository (`~/.hermes/factory/`):

```bash
factory status
```

Report succinctly to the owner:
- **Milestones & Merges**: which milestones merged fast-forward on green and which are pending/stopped.
- **Gate & Evidence**: exact `PASS` / `FAIL` / `NOT_RUN` check statuses (`result.json`), wall time, and attempts used.
- **Interventions & RFIs**: human decisions recorded via `factory note` (separating product decisions from factory bugs) and any open entries in `RFI.md`.
- **Next Action**: exact command or owner checkpoint needed next (never claim completion when a gate is red, stale, or budget-exhausted).
