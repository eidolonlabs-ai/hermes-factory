# Headless CLI ChronoGraph intake result

Date: 2026-11-16 (America/Los_Angeles). Mode: headless `codex exec`, CLI 0.169.0, configured default model (not independently pinned for this comparison). Run `[local run identifier omitted]` completed in 46.33 seconds.

Outcome: **needs_clarification**, 7 questions, 6 blocking. The original source and intake workspace remained unchanged. No application was built. The saved report was inspected locally; raw session records are not published.

Caught: bitemporal versus mutable-history mismatch; late and equal-time conflict rules; identical-assertion evidence; PostgreSQL/Neo4j acknowledgment and retry semantics; non-idempotent Cypher; historical visibility; missing E2E service and optional verification; destructive reset; retraction scope; local versus enterprise deployment.

Partial/missed: concurrency was mentioned as an invariant but not directly developed into an owner question; concrete API response/error/pagination contracts were not elicited; extraction rules and JSON health validation were proposed as assumptions rather than elicited in questions. UI-specific omitted controls received little attention. This is useful behavior, not a claim of complete ambiguity coverage.

The generic prompt did not include evaluator categories or previous results. The local session inherited account environment and may have inherited global instructions/skills/memory. This is not a clean-room or sealed-holdout result. One run cannot establish superiority over another template.

The first attempt inside the outer tool sandbox failed before model execution because Codex could not initialize its session database/app server. The successful retry ran with outer host authorization while the child Codex invocation retained its read-only sandbox. No child sandbox bypass was used.

This result is separate from the [Desktop-native intake](desktop-native-intake.md). It does not verify Desktop role discovery, Worktree UI, or app hooks.
