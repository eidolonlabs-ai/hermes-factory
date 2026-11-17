# Clarifications from the product owner

These are the clarifying questions asked about `HANDOFF.md` before planning, with the
answers the product owner chose. They are binding requirements alongside `HANDOFF.md`.

## 1. Out-of-order / backdated episodes
**Q:** How should the conflict engine handle out-of-order / backdated episodes (where a
newly ingested episode has `valid_from` earlier than an already-ingested active fact for
the same functional `(subject, predicate)`)?

**A:** Out-of-order support: insert the historic fact as `superseded` with
`valid_until = newer_fact.valid_from` if a newer fact already exists; split/adjust
overlapping intervals.

## 2. Re-asserting the currently active fact
**Q:** When a new episode re-asserts the exact same `(subject, predicate, object)` as the
currently active fact, how should the engine behave?

**A:** Idempotent no-op: keep the existing active fact open (no new fact row, or link the
episode without superseding).

## 3. Extractor input formats
**Q:** For the deterministic Markdown/text episode extractor, what input formats should
it parse out of the box?

**A:** Structured triple syntax (`[Subject] --PREDICATE--> [Object]` or
`Subject | PREDICATE | Object`) plus natural-language pattern matching for common verbs
(`has IP`, `is assigned to`, `status is`, `role is`, `located in`, `version is`).

## 4. Retraction
**Q:** How should the `'retracted'` status in `fact_ledger` be triggered and exposed?

**A:** Both: allow manual retraction (`POST /api/facts/{id}/retract`) AND support
negative/retraction statements in episodes (e.g. `RETRACT: Subject | PREDICATE | Object`).
