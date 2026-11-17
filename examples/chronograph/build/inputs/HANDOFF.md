# Project Handoff: ChronoGraph (Temporal Knowledge Graph & Fact Conflict Engine)

## 1. Objective
Build and verify a complete, containerized full-stack application in Docker Compose that ingests text/structured episodes, extracts temporal SPO triples `(subject, predicate, object, valid_from, valid_until)`, automatically resolves contradicting facts on functional predicates, projects the live temporal graph into Neo4j, and provides an interactive React UI with a "Time-Travel" scrubber and conflict lineage inspector.

## 2. Stack & Container Architecture
- `db` (PostgreSQL 16-alpine, port 5432): Immutable source-of-truth ledger storing `episodes`, `extraction_logs`, and `fact_ledger` (`id`, `subject`, `predicate`, `object`, `valid_from`, `valid_until`, `status` ['active'|'superseded'|'retracted'], `superseded_by_id`, `episode_id`, `neo4j_synced_at`).
- `graph` (Neo4j 5 Community, ports 7474/7687): Live property graph storing `:Entity` nodes and temporal `:FACT` relationships (`predicate`, `valid_from`, `valid_until`, `status`, `fact_id`, `episode_id`). Must include a `cypher-shell` healthcheck with `start_period: 40s`.
- `api` (FastAPI Python 3.12, port 8000): Async SQLAlchemy/SQLModel + official `neo4j` Python `AsyncGraphDatabase` driver managed in FastAPI `lifespan` (always passing `database_="neo4j"`).
- `web` (React 19 + Vite + TypeScript + Tailwind, port 3000): Interactive force-directed/SVG graph canvas, Temporal Scrubber slider (`as_of` timestamp filter), Episode Ingestion drawer, "Load Multi-Episode Conflict Demo" button, and Conflict Lineage Inspector.
- `e2e` (Playwright): End-to-end browser verification hitting `http://localhost:3000`.

## 3. Core Functional Rules
1. **Functional Predicate Superseding:** Predicates in `FUNCTIONAL_PREDICATES` (e.g., `HAS_IP`, `CURRENT_ROLE`, `STATUS`, `LOCATION`, `ASSIGNED_TO`, `VERSION`) allow only one `active` object per subject at a time. When a new episode asserts a different object for an existing active `(subject, predicate)`, the engine atomically:
   - Sets `valid_until = new_fact.valid_from` and `status = 'superseded'` on the prior fact in Postgres and Neo4j.
   - Inserts the new fact as `status = 'active'`, `valid_until = NULL`.
   - Links the old and new facts via `superseded_by_id` in Postgres and a `[:SUPERSEDED_BY]` edge or property in Neo4j.
2. **Zero-Key Deterministic Demo & Extractor:** Provide a deterministic Markdown/SPO triple extractor AND a `POST /api/demo/seed` endpoint that loads 4 chronological infrastructure/team episodes with deliberate contradictions so all features and E2E tests work out-of-the-box without requiring paid external LLM API keys.
3. **Time-Travel Querying:** `GET /api/graph?as_of=<ISO8601>` returns only nodes and edges where `valid_from <= as_of` AND (`valid_until IS NULL` OR `valid_until > as_of`), plus optional ghost/superseded edges for lineage inspection.

## 4. Execution & Verification Contract
- Redirect verbose `docker compose build` and test outputs to `/tmp/*.log` and inspect only summaries/tails to preserve context window hygiene.
- Commit to git after each passing milestone:
  1. Infrastructure & Dual-DB Heartbeat (`GET /api/health` -> `{postgres: "ok", neo4j: "ok"}`)
  2. Temporal Storage, Conflict Engine & 4-Episode Seed Dataset
  3. REST API & Live Container Pytest Integration Suite (zero DB mocks)
  4. React Frontend (Graph Canvas + Time-Travel Slider + Conflict Inspector)
  5. Playwright E2E Suite & `/browser` visual verification on `http://localhost:3000`
