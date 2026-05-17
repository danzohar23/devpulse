# Architecture Decision Records

## ADR-001: Repository pattern for all DB access

**Decision**: All database access is funnelled through `src/pulse/db/repository.py`. No other module imports the SQLAlchemy engine or executes queries directly.

**Why**: Keeps the data layer testable in isolation. Tests can swap the DB engine (e.g. SQLite in-memory) without touching business logic. Makes future migrations or DB engine swaps lower-risk.

## ADR-002: Sync httpx for the ingestion worker

**Decision**: The GitHub client uses synchronous httpx, not async.

**Why**: The ingestion worker is a simple sequential script — fetch commits, upsert, fetch PRs, upsert, etc. Async would add complexity (event loops, async context managers) without meaningful throughput gain for a single-worker, rate-limited script.

## ADR-003: pgvector for embeddings storage

**Decision**: Store embeddings as `vector(1536)` columns in the same Postgres database rather than a separate vector store.

**Why**: Simplifies the deployment (one database, not two). pgvector's HNSW index is fast enough for personal-scale data. Avoids keeping two stores in sync.

## ADR-004: MCP between agent and DB

**Decision**: The Claude agent reaches data exclusively through MCP tools, not by querying the DB directly.

**Why**: Decouples the agent from the schema. Tools can be evolved, renamed, or reimplemented without touching the agent prompt. Tools also provide a natural place to add authorisation checks.

## ADR-005: Pydantic models as the data contract

**Decision**: All GitHub API responses are parsed through Pydantic models before any other code touches them. SQLAlchemy ORM models are a separate layer.

**Why**: Makes the data contract explicit and validated at the boundary. Prevents raw dicts from leaking into business logic. ORM models and Pydantic models are kept separate because their purposes differ (persistence vs. validation/transport).
