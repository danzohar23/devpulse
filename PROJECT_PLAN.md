# Pulse — Project Plan

## Milestone 1: Ingestion and storage ✅
- GitHub REST client with retry + rate-limit handling (tenacity, httpx)
- PostgreSQL schema with pgvector extension (`schema.sql`)
- SQLAlchemy async ORM models (`CommitRecord`, `PullRequestRecord`, `IssueRecord`)
- Repository pattern — all DB access through `db/repository.py`
- Ingestion worker script (`python -m pulse.ingestion.worker`)
- FastAPI app skeleton with `GET /health`

## Milestone 2: REST API + RAG ✅
### REST API
- `GET /commits` — repo filter, limit (1–200)
- `GET /pull_requests` — repo filter, state filter (`open`/`closed`), limit
- `GET /issues` — repo filter, state filter, limit
- FastAPI dependency injection for DB sessions (`api/dependencies.py`)
- Input validation via `Query(ge=1, le=200)` and `Literal["open", "closed"]`
- Full test coverage via `httpx.AsyncClient` + SQLite in-memory fixture

### RAG / Indexing
- `VectorType` SQLAlchemy TypeDecorator — pgvector on PostgreSQL, JSON text on SQLite
- `EMBEDDING_DIM = 1536`, `SearchResult` Pydantic model
- `embedding` column on all three ORM records
- `embed_texts()` — OpenAI `text-embedding-3-small`, batched in groups of 100
- Incremental indexer (`python -m pulse.indexing.indexer`) — fetches unindexed records, embeds, writes back; DB connection closed during network I/O
- Repository functions: `get_unindexed_*`, `set_*_embedding`, `search_similar`
- `search_similar` — cosine distance via pgvector `<=>`, searches all three tables, re-ranks globally; raises `NotImplementedError` on non-PostgreSQL (ADR-013)
- HNSW indexes in `schema.sql` (`vector_cosine_ops`)

## Milestone 3: MCP server ✅
- `mcp.Server` initialised with stdio transport (`python -m pulse.mcp.server`)
- Four tools, all calling repository layer only (ADR-001 / ADR-004):
  - `search_activity(query, repo?, limit)` — embeds query with `embed_texts`, calls `search_similar`
  - `get_commits(repo?, limit)` — calls `get_recent_commits`
  - `get_pull_requests(repo?, state?, limit)` — calls `get_recent_pull_requests`
  - `get_issues(repo?, state?, limit)` — calls `get_recent_issues`
- Business logic extracted into `tool_*` module-level functions for direct testability
- 15 tests in `tests/test_mcp_tools.py`; `search_activity` tests mock `embed_texts` + `search_similar`

## Milestone 4: Agent ✅
- `claude-sonnet-4-5` tool-use loop in `src/pulse/agent/agent.py`
- Spawns `pulse.mcp.server` as a subprocess over stdio (ADR-014) — no direct import of tool functions
- Multi-round tool-use loop: tool_use blocks → MCP calls → tool_result blocks → continue until `end_turn`
- System prompt forbids answering from memory; every answer must be tool-grounded (ADR-014)
- All tool calls and results logged at INFO
- 11 tests in `tests/test_agent.py` covering: no-tool path, single tool call routing, tool_result message shape, MCP tool catalogue forwarding, multi-round loops, parallel tool calls in one turn, error propagation, and INFO logging

## Milestone 5: Polish (TODO)
- APScheduler for automatic ingestion on a configurable interval
- CLI entrypoint (`pulse query "..."`)
- Observability: structured logging, OpenTelemetry traces, Prometheus metrics
- API authentication (API key header or OAuth)
