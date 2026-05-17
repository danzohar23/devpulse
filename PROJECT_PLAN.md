# Pulse — Project Plan

## Milestone 1: Ingestion and storage ✅
- GitHub REST client with retry + rate-limit handling
- PostgreSQL schema with pgvector extension
- SQLAlchemy async ORM models
- Repository pattern for all DB access
- Ingestion worker script
- FastAPI app skeleton with /health

## Milestone 2: Indexing (TODO)
- OpenAI / Anthropic embeddings for commit messages, PR bodies, issue bodies
- Batch embedding job in `indexer.py`
- pgvector index (ivfflat or hnsw) for ANN search
- `search_similar(query_embedding, limit)` in repository.py

## Milestone 3: MCP server (TODO)
- MCP server exposing tools:
  - `search_activity(query: str, since: str, repo: str | None)`
  - `get_commits(repo: str, limit: int)`
  - `get_pull_requests(repo: str, state: str, limit: int)`
  - `get_issues(repo: str, state: str, limit: int)`
- All tools return structured JSON the agent can reason over

## Milestone 4: Agent (TODO)
- Claude tool-use loop calling MCP tools
- Natural language query → structured tool calls → synthesised answer
- Streaming responses via FastAPI SSE

## Milestone 5: Polish (TODO)
- APScheduler for automatic ingestion
- CLI entrypoint
- Observability (structured logs, traces)
- API authentication
