# Desktop native ChronoGraph intake result

Date: 2026-11-16 (America/Los_Angeles). Mode: native subagent in the active Codex Desktop chat, task a native subagent, fresh conversation context. Role instructions were explicitly supplied from architect.toml and architect-intake/SKILL.md; automatic custom-role discovery was not exercised. Model and permissions were inherited from the parent; no claim of a separate read-only sandbox is made.

The child was allowed only the original DOCX and those two generic instruction files. It extracted the DOCX in memory. Evaluator rubric, previous CLI result, and coordinator diagnosis were not supplied. The returned report states it read only those inputs, made no edits, ran no embedded commands, and started no implementation. The original source hash was rechecked by the coordinator.

**Outcome: needs_clarification.** Fourteen prioritized questions returned to the coordinator. Items 1–12 were blocking; item 13 was conditional on deployment scope; item 14 was nonblocking for core architecture. The user has not answered them; this benchmark intentionally stops at intake.

## Questions returned

1. Valid-time history or full bitemporal knowledge history? Cites §1 bitemporal/append-only claims versus §3 mutable fields. Changes storage, audit and query model.
2. What happens for late or future observations, and how does observed_at map to valid_from? Cites §3 active-only replacement algorithm. Changes interval correction and lineage.
3. How do equal timestamps, concurrent writes, and repeated assertions resolve? Cites single-valued predicate invariant versus same-object insertion. Changes transaction and duplicate rules.
4. What should as_of and include_superseded show? Cites §4 and §5. Distinguishes current status from historical validity and proposes half-open intervals explicitly as an assumption.
5. What acknowledgment, stale-read, retry and rebuild guarantees connect PostgreSQL and Neo4j? Cites source-of-truth, synced marker and ingestion response. Changes durable recovery design.
6. Is behavioral idempotency authoritative over sample Cypher, and should projection target exact fact IDs? Cites MERGE promise versus CREATE and broad invalidation.
7. Is retraction in scope, when is it effective, and does it restore predecessors? Cites declared status without corresponding API/filter.
8. What grammar, normalization and atomic/partial failure behavior should extraction support? Cites pipe-delimited input versus annotated seed and raw-text endpoint.
9. Which health/seed response contract is authoritative? Cites JSON response versus bare-string shell comparisons. Proposes structured JSON checks as an assumption.
10. May verification/reseeding delete existing data, in what environments, and what if reset overlaps ingestion or partially fails? Cites seed reset and volume deletion in a proposed hook.
11. Where does the fifth/E2E service run, must missing browser tests fail, and is web health required? Cites service table versus Compose/script omissions.
12. What response/error/order/pagination/lineage schemas and minimum acceptance outcomes must be fixed? Cites description-only responses and vague completion gate.
13. Trusted single-user demo or enterprise/shared deployment? Cites enterprise wording versus local credentials/ports. Proposed local-only default requires owner confirmation.
14. Are autoplay, title/observation-time inputs, and selection behavior during scrubbing required? Cites UI mockup versus component/API details.

This is a coordinator summary of the native agent's returned report; raw session transcripts are kept private.

## Caught and missed

Caught all twelve topic areas in the proposed rubric, plus UI gaps. Explicit concurrency and API-contract questions were clearer than in the single CLI run. This is a qualitative observation, not a controlled comparative score.

Partial: the repeated-assertion question covers fact duplication but does not explicitly settle a client-supplied episode request idempotency-key contract. Timezone/offset parsing and graph-size/performance limits were not explored deeply. Those are follow-up areas, not grounds to invent requirements. Some proposed assumptions (half-open intervals, demo fact counts, local-only scope) still need approval.

No numerical score is assigned: there is only one native run, settings were not matched/pinned against other templates, and the scorer is the coordinator. This record proves observed question-elicitation behavior, not comprehensive architect reliability.

UI acceptance remains pending at the user's explicit request. The computer-use tool refused access to the Codex application. No automatic role discovery, new-chat Worktree selection, or parallel builder UI run is claimed.
