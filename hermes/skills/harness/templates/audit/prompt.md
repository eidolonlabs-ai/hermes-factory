You are auditing a codebase cold. You have never seen it before. This is a READ-ONLY audit:
do not modify, create or delete any files, do not run docker, servers, package installs or
network calls. Read code (and run read-only git/grep/ls if available).

The product requirements are in `HANDOFF.md` and `CLARIFICATIONS.md` at the repo root.

Task: Review the codebase for logic bugs, race conditions, and edge cases in <core domain
logic> and <cross-store sync>. Also report any place where the implemented behaviour
contradicts HANDOFF.md or CLARIFICATIONS.md, and significant UI bugs in <key UI parts>.

Only report CONFIRMED bugs: for each, you must be able to name the exact code location and a
concrete input/sequence that produces wrong behaviour. Do not report style issues, missing
docs, hypothetical hardening, or test-quality opinions. Severity:
- high: wrong data / lost or corrupted facts / spec violation a user would hit in normal use
- medium: wrong behaviour in a realistic edge case or concurrency scenario
- low: minor or unlikely edge case

Output format: after your investigation, reply with ONLY a fenced ```json block containing
{"findings": [...]} where each finding has keys id, severity (high|medium|low), area
(conflict-engine|neo4j-postgres-sync|concurrency|temporal-query|extractor|api-contract|ui|other),
title, location, repro, expected, actual. Keep each field concise. Read files individually;
do not dump many files at once.
