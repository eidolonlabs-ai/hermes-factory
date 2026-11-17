# ChronoGraph audit: hermes-agent-harness build (2026-11-17)

Same cold, read-only audit as `audit-2026-11-16.md` (same `prompt.md` and `schema.json`), run
by Codex (high) and Claude Opus (high) on a clean clone of the harness build at `0d50bd6`
(after M5). The requirement files were placed at the repo root as in the earlier audits.
Raw output: `findings-2026-11-17-harness.json`.

## Deduplicated findings: 4 (Codex 2, Claude 3, 1 overlap)

| # | Sev | Finding | Found by | Live-verified |
|---|---|---|---|---|
| 1 | high (Codex) / med (Claude) | Neo4j commits before Postgres; if the Postgres commit then fails (process killed, connection lost), Neo4j keeps a fact the ledger never committed and nothing reconciles it | codex+claude | no (needs fault injection); recorded by the M2/M3 reviewers as an accepted risk |
| 2 | med | Backdated assertion of the *currently active* object is a no-op, so the interval is not split (rule R0 from RFI #4 overrides Clarification 1 in this case) | claude | **yes**: seed, then `web-01 status is healthy` @ 2025-03-15 → `noop`; `as_of=2025-03-20` still `degraded` |
| 3 | med | Scrubber input loses sub-millisecond digits (`Date.parse`), so it queries 456 µs before a microsecond boundary | codex | no |
| 4 | low | In time-travel mode edges in force at `as_of` are coloured by their *current* status (look superseded) | claude | no |

## Comparison (same audit, same inputs)

| Build | Unique findings | High |
|---|---|---|
| Antigravity (`/goal`, `/run-workflow`) | 13 | 2 (both live-verified) |
| Hermes forge (2026-11-16) | 7 | 0 |
| **hermes-agent-harness** | **4** | **1 by Codex's rating**: the same dual-write issue rated medium in the Antigravity audit; not live-verified |

Finding 1 is the class Antigravity's #3 also had ("Neo4j writes commit before Postgres").
Finding 2 is the class of Antigravity's #10/#11 (backdated assertions of an existing object).

## Notes
- Both audits finished in about 4 minutes, much faster than the previous round.
- The harness build has more tests to read (171 integration, 42 holdout, 47 Playwright) and
  a written decision log (`RFI.md`, 37 entries) that the auditors used to separate intended
  behaviour from bugs.
