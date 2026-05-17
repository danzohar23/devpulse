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

## ADR-006: FastAPI dependency injection for DB sessions

**Decision**: The API layer gets its `AsyncSession` via a `get_db_session` dependency function in `api/dependencies.py`, injected through FastAPI's `Depends()`. Tests override this dependency via `app.dependency_overrides` to inject an in-memory SQLite session.

**Why**: The alternative — passing a session factory or global engine directly into route functions — makes tests harder to isolate and couples routes to the engine module. `dependency_overrides` is FastAPI's first-class testing seam: it lets tests swap the entire DB without monkey-patching or environment tricks. The session-per-request lifecycle (commit on success, rollback on exception) is implemented once in the dependency rather than repeated in every route handler.

## ADR-007: Limit cap at 200 on all list endpoints

**Decision**: Query param `limit` is validated `ge=1, le=200` via FastAPI's `Query()`. Requests outside this range return 422 automatically.

**Why**: Uncapped limits expose the service to accidental or malicious large fetches that could exhaust memory or swamp the DB. 200 is generous for an activity-query API while staying well clear of OOM territory. Callers needing more should page by timestamp. The validation is done by Pydantic/FastAPI at the boundary — no repository-level guard is needed.

## ADR-008: State filtering kept in repository, not the route

**Decision**: The `state` filter (`open` / `closed`) is applied inside `get_recent_pull_requests` and `get_recent_issues` in `repository.py`, not in the route handler.

**Why**: Routes should translate HTTP concerns (query params, response serialisation) into domain calls — they shouldn't build SQL predicates. Keeping filters in the repository preserves the single-access-point rule from ADR-001 and means future callers (e.g. the MCP tools in Milestone 3) get the same filtering for free without duplicating logic.

## ADR-009: No auto-migration in the API lifespan

**Decision**: The FastAPI `lifespan` hook does not call `run_migrations()`. Schema setup is the responsibility of the worker or a dedicated migration step, not the API process.

**Why**: Running DDL at API startup is risky in multi-replica deployments (concurrent migrations, lock contention). It also obscures whether a migration succeeded or failed. Keeping migrations explicit — run once by the worker or a separate CLI step — makes the behaviour predictable and easy to verify in CI.

## ADR-010: Sync/async architecture split

**Decision**: The API and database layer are fully async (FastAPI, SQLAlchemy async engine, `AsyncSession`). The ingestion worker is a synchronous, sequential script that uses a sync `httpx.Client`. The worker's async shell (`ingest_repo`, `main`) is driven by a single `asyncio.run()` call at the entry point, which is the only place an event loop is created.

**Why — API must be async**: FastAPI runs on an ASGI server (uvicorn). Handling concurrent HTTP requests without blocking requires async I/O throughout: from the route handler down through the database session. A sync SQLAlchemy session inside an async route would block the event loop during every query, serialising all requests and defeating the purpose of an async server.

**Why — worker stays sync**: The ingestion worker is a single-process, sequential job: fetch commits → fetch PRs → fetch issues → write to DB → repeat for the next repo. There is no concurrency to exploit. Making the GitHub client async would require `async with httpx.AsyncClient()`, async retry logic, and running inside an already-active event loop — complexity that yields no throughput benefit for a rate-limited, sequential workload.

**Why `asyncio.run()` is safe here**: The worker calls `asyncio.run(main())` once at startup. `asyncio.run` creates a fresh event loop, runs the coroutine to completion, and shuts the loop down before returning. The sync GitHub client is called *between* awaits — specifically, all network I/O finishes before `async with get_session()` opens — so the blocking `httpx` calls never execute inside a running event loop. This is the correct pattern: sync blocking work happens outside the async context; the async context is only entered for database writes. The alternative — running the sync client inside `asyncio.get_event_loop().run_in_executor()` — would be necessary only if the worker were embedded in a long-lived async service that needed to remain responsive while waiting on the GitHub API.
