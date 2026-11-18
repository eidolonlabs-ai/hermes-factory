# Benchmarking a factory build against another tool

Used for ChronoGraph (Antigravity vs Hermes forge 2026-11-16, vs hermes-factory 2026-11-17). Load when the user wants a
fair head-to-head or a quality score for a finished build.

## Fair inputs
- Give the factory exactly what the other tool got: the same handoff file (check `shasum`), plus
  every answer the user gave in that tool's clarifying interview, plus a count of mid-run
  nudges (each one is an intervention for that tool).
- Do not hand over richer docs the other tool never saw (e.g. the master spec it was
  distilled from).
- Verify provenance before labelling a file "the benchmark input": compare `shasum` and, for
  docx vs md, normalized text similarity. ChronoGraph has TWO inputs: the 607-line master
  spec (= the codex template's `original.docx`; an intake benchmark scored with a rubric the
  architect must never see) and the 28-line `HANDOFF.md` + 4 clarifications that both builds
  actually received (the build benchmark). Users may call either "the spec we used".
- Contamination: if you already know bugs the other tool found later, never put them in
  prompts, AGENTS.md, specs or review checklists. Keep review prompts generic.
- Only environment deltas are allowed (shifted host ports, compose name), in
  `inputs/ENVIRONMENT.md`, labelled as not-product-requirements.

## Recovering an Antigravity session (local)
- Conversations: `~/.gemini/antigravity/conversations/<uuid>.db` (SQLite; open
  `file:<path>?immutable=1`). Table `steps(idx, step_type, step_payload blob, ...)`;
  payloads are protobuf, so pull printable strings.
- step_type 14 = user input, 15 = model message, 132 = tool result. The launch session is the
  big one whose step 0 mentions the handoff; subagent sessions start with role prompts
  ("Audit ...", "You are fixing BUG-n").
- Interview answers appear as an `ask_question` tool call (questions + options) followed by
  the model's "We are aligned on..." summary. Created-At timestamps in tool results give the
  timeline.
- Antigravity's interview payload marks the recommended option with "(Recommended)".

## Metrics to record
| Metric | Source |
|---|---|
| Human interventions | other tool: user inputs in the session; factory: `factory note` count. Split into user decisions (launch, approvals) vs factory/tool bugs: only the first measures babysitting |
| Wall time | session timestamps / git log vs card + run timestamps; subtract time spent waiting on the user's replies at checkpoints |
| Gate first-pass rate | `result.json` attempts per run |
| Bugs fixed during build | `docs/reviews/M*.md` findings |
| Bugs remaining | cross-vendor audit below |
| Cost | claude `total_cost_usd`; codex `turn.completed` usage tokens |

## Cross-vendor audit (score remaining bugs)
1. Clean clones into `~/.hermes/factory/audits/<name>/repo-<x>/` with `git clone`; copy the SAME
   requirement files into each at the clone ROOT (the prompt names them there; factory
   projects keep them in `inputs/`); strip process artifacts that would bias the auditor
   (`docs/reviews`, `RFI.md`, `.forge`, `.factory`, `inputs/` other than the copied files) — every build, same treatment, or the
   counts are not comparable. Commit the snapshot in each clone.
2. Copy `templates/audit/{prompt.md,schema.json,run.sh}`; fill the `<...>` focus slots in
   prompt.md with the same wording the user used for the other tool's review pass.
3. Run `run.sh <x> <y>` through the `terminal` tool with `background=true, notify=true`.
4. Parse: codex `codex-<x>.json` is schema JSON; claude `claude-<x>.json` has a `result`
   string with a fenced json block (check `is_error`/`terminal_reason` first).
5. Dedupe across auditors by location + behaviour; take max severity.
6. Live-verify every high (and the worst item per repo) against the running stacks with
   unique entity names; note "verified" in the report. Write `REPORT.md` there.
7. Report per-auditor counts separately: an auditor going easy on code it wrote shows up
   as a gap between auditors.

## ChronoGraph result (reference point)
- Antigravity: 8 interventions, 13 remaining findings (2 high, both live-verified).
- Forge: 2 interventions, 7 remaining (0 high); 15 bugs fixed by cross-vendor review
  during the build; 12/12 runs passed the gate first try; ~3h15m run time.
- Auditor overlap was low (4 and 0): counts are lower bounds.
- Follow-up M6 card fixed 5 findings in 31 min with one more found by review.
- hermes-factory: 6 interventions (3 were factory bugs on its first real run), 4
  remaining findings (1 high by Codex's rating), M4/M5 passed first try, ~3h30m build time.
