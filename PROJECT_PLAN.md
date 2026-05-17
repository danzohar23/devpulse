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
- `search_similar` — cosine distance via pgvector `<=>`, searches all three tables, re-ranks globally; returns `[]` on non-PostgreSQL (safe for tests)
- HNSW indexes in `schema.sql` (`vector_cosine_ops`)

## Milestone 3: MCP server (TODO)
- Initialise `mcp.Server` with stdio transport
- Register tools (all call repository layer, never the DB directly):
  - `search_activity(query: str, since: str, repo: str | None) -> list[dict]` — embeds query, calls `search_similar`
  - `get_commits(repo: str, limit: int) -> list[dict]`
  - `get_pull_requests(repo: str, state: str, limit: int) -> list[dict]`
  - `get_issues(repo: str, state: str, limit: int) -> list[dict]`
- Tool tests in `tests/test_mcp_tools.py`

## Milestone 4: Agent (TODO)
- Claude tool-use loop (`claude-sonnet-4-6`) calling MCP tools
- Natural language query → structured tool calls → synthesised answer
- Streaming responses via FastAPI SSE (`POST /query`)
- Agent tests

## Milestone 5: Polish (TODO)
- APScheduler for automatic ingestion on a configurable interval
- CLI entrypoint (`pulse query "..."`)
- Observability: structured logging, OpenTelemetry traces, Prometheus metrics
- API authentication (API key header or OAuth)
