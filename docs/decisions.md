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

## ADR-011: Fatal vs. skippable errors in the ingestion loop

**Decision**: The per-repo exception handler in `main()` distinguishes between two classes of failure. Repo-specific errors (network blips, 404s, transient 5xx that survive retries) are logged and skipped — the worker continues to the next repo. Token-level errors (HTTP 401, 403) and exhausted rate-limit retries (HTTP 429 after tenacity gives up) are logged at `CRITICAL` and re-raised, aborting the entire run.

**Why**: A broad `except Exception: log and continue` is wrong for token failures. If the GitHub token is invalid or lacks `repo` scope, every subsequent API call will return 401. Silently skipping all repos and exiting cleanly creates a false impression of success — operators see "Ingestion complete" in the logs and no data moves. The same argument applies to a 429 that has survived all tenacity retries: if the rate limit is truly exhausted, every remaining repo will hit the same wall within milliseconds. Continuing wastes connection overhead and produces a log full of identical failures. Aborting immediately makes the failure mode unambiguous and easy to alert on.

**How to apply**: `httpx.HTTPStatusError` is caught first. Status 401 or 403 → log `CRITICAL` + re-raise. Status 429 → log `CRITICAL` + re-raise (tenacity only surfaces this after all retry attempts are spent). Any other `HTTPStatusError` (e.g. 404 for a deleted repo, 422, transient 5xx that slip through) → log `ERROR` + skip. All non-HTTP exceptions (DB errors, parse errors) → log `ERROR` + skip, so a broken repo does not kill the whole run.

## ADR-012: Embedding model changes require a full re-index

**Decision**: Switching the embedding model (currently `text-embedding-3-small`) mid-project is a breaking change that requires re-indexing every record. The new model must be rolled out in a dedicated migration step: clear all existing embeddings, run the incremental indexer to completion, then deploy the new code.

**Why**: Embeddings from different models live in incompletely different spaces. Even when two models share the same output dimension (e.g. both produce 1536-dimensional vectors), their coordinate systems are unrelated — a cosine distance computed between a vector from model A and a vector from model B is meaningless. Mixing old and new embeddings in the same table will corrupt `search_similar` results silently: queries will match by numerical coincidence rather than semantic similarity, and the degradation is invisible in the application logs.

**How to apply**: Before changing `_MODEL` in `embedder.py`, run a migration that sets `embedding = NULL` on every row in `commits`, `pull_requests`, and `issues`. Then run the indexer with the new model. Do not deploy the new `_MODEL` value while any rows still hold embeddings from the old model. Treat any commit that changes `_MODEL` as a migration commit — increment the schema version and document it in this file.

## ADR-013: `search_similar` raises `NotImplementedError` on non-PostgreSQL backends

**Decision**: `search_similar` raises `NotImplementedError` with a clear message when the underlying database is not PostgreSQL. It does not silently return an empty list.

**Why**: Silent degradation is a trap. Returning `[]` on SQLite was convenient for running the test suite, but it means any caller on a non-PostgreSQL backend gets a plausible-looking "no results" response rather than an immediate, unambiguous error. A caller that doesn't know the function is a no-op on its backend will make wrong decisions — the agent would confidently report "nothing found" rather than "this feature is unavailable." Raising `NotImplementedError` makes the constraint visible at the call site and forces callers (including tests) to be explicit: either mock the function, skip the test, or run against a real PostgreSQL instance. The test that previously asserted `results == []` on SQLite has been updated to assert that the error is raised instead.

## ADR-014: Agent talks to the MCP server over stdio, not via direct import

**Decision part 1**: The agent in `src/pulse/agent/agent.py` spawns `pulse.mcp.server` as a subprocess using the MCP Python SDK's `stdio_client` and communicates with it via the MCP wire protocol. It does **not** import the server's tool functions and call them in-process, even though both modules live in the same package.

**Why subprocess**: ADR-004 declared MCP as the boundary between the agent and the data layer. Honouring that boundary at the *runtime* level — not just the API level — has three concrete benefits:

1. **No drift between tested and shipped behaviour.** A third-party client (Claude Desktop, a future hosted runtime, another agent on the same network) would reach the tools over stdio. If the agent in this repo took a shortcut and imported the tool functions directly, the agent's call path would diverge from every other client's call path. Schema mismatches, serialisation bugs, and protocol-level errors would only show up in production. Routing through the same subprocess that other clients use guarantees the agent exercises the actual wire format.
2. **Dependency isolation.** The agent process needs Anthropic + the MCP client. The server process needs SQLAlchemy, pgvector, OpenAI, and the GitHub client. Keeping them in separate processes means a tool dependency upgrade (e.g. a SQLAlchemy major version bump) cannot break the agent's startup, and a crash in a tool handler cannot take down the agent loop.
3. **Faithful to MCP's design.** MCP is a wire protocol with a transport layer. Using `Server.run(read_stream, write_stream, ...)` only to then bypass the streams in tests would mean we're not actually testing the protocol surface — we'd be testing a Python function call wearing an MCP costume.

**Decision part 2**: The system prompt instructs the agent to **always use tools to ground its answers** and to refuse to answer from memory.

**Why no-memory**: The agent's job is to answer questions about the user's *private* GitHub activity. That data is not in Claude's training set and cannot be in Claude's training set — by definition it post-dates training and belongs to one user. Any answer "from memory" is therefore not memory at all; it is a hallucination dressed up as a plausible-sounding summary of what a typical developer might do. Three concrete failure modes the no-memory rule prevents:

- *"Confident wrong"*: Claude could plausibly say "you opened three PRs about authentication last week" because that pattern is common in training data. Without a tool call, that sentence has no truth value. The user can't tell.
- *"Soft refusal that looks like data"*: Claude could say "I don't see much activity around X" without ever having queried. The user reads this as "no activity found" instead of "no query was run."
- *"Backed-into-a-corner hedging"*: Asked a question whose tool path is unclear (e.g. an aggregation the tools don't directly support), Claude might invent an estimate rather than admit the gap. With the no-memory rule, the model is forced either to compose a tool call that *does* answer the question or to say plainly that the tools don't cover it.

The rule also doubles as a debugging aid: every meaningful answer corresponds to a tool call visible in the INFO logs. An answer with no tool call in the logs is, by policy, a bug.
