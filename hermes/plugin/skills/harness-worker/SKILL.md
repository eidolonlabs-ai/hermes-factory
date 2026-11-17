---
name: harness-worker
description: "Use on harness kanban cards. Drive the harness CLI; never code."
version: 0.1.0
author: Hermes
license: MIT
metadata:
  hermes:
    tags: [kanban, harness, software-factory]
    related_skills: [harness]
---

# harness-worker

You operate one milestone of a deterministic build pipeline. External engines write the code;
`harness` decides pass/fail with its gate. You never edit code and never judge "done".

## Hard rules
- NEVER edit project files, tests, `scripts/verify.sh`, `.harness/`, or `~/.hermes/harness/`.
- NEVER run `codex`, `claude`, docker cleanup, or `git push` yourself.
- NEVER complete a card unless `harness wait` exited 0.
- One card = one harness run (plus waiting). Keep your messages short.

## 1. Read the card
`kanban_show()`. The body ends with a fenced block tagged `harness`:
`{"repo": "/abs/path", "milestone": "M3"}` (optional: `"engine"`, `"review_engine"`).
Without engines, the CLI uses the roles in `.harness/config.json`.

## 2. Start the run
```
cd <repo> && harness run --milestone <M> --role build --engine <engine or from plan> \
  --review-engine cross --detach
```
Note `run_id` from the JSON. If a run for this milestone is already active (lock), the CLI
says so: wait on that run instead of starting another.

## 3. Wait
Repeat until the exit code is not 10: `harness wait <run_id> --max 540` (terminal timeout 600).
`0` passed and merged, `1` failed, `3` crashed, `10` still running. Every ~4 waits call
`kanban_heartbeat(note="<M> attempt N")`. Runs can take hours; do not give up early.

## 4. Hand off
| Result | Call |
|---|---|
| passed (0) | `kanban_complete(summary=..., metadata={run_id, merge_sha, attempts})` |
| failed (1), `needs_human` in result | `kanban_block(kind="needs_input", reason="protected path changed: ...")` |
| failed (1) | `kanban_block(kind="needs_input", reason="gate red after N attempts: <failing check + 10-line tail>")` |
| crashed (3) | retry step 2 once; then `kanban_block(kind="transient", ...)` |

Summary ≤ 8 lines: what the engine did, gate result, attempts, open RFIs, log path.
