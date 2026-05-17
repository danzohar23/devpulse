# Pulse

A personal data agent that ingests your GitHub activity, stores and indexes it, and lets you query it in natural language through an AI agent.

## Demo

```
> pulse query "What did I work on last week?"
I found 12 commits across 3 repositories last week...
```

## Architecture

```
GitHub API → Ingestion Worker → PostgreSQL (pgvector)
                                      ↓
                              MCP Server (tool layer)
                                      ↓
                           Claude Agent (natural language)
                                      ↓
                              FastAPI REST API
```

- **Ingestion worker**: polls GitHub REST API on a schedule, upserts commits/PRs/issues
- **PostgreSQL + pgvector**: stores structured data plus vector embeddings for semantic search
- **MCP server**: exposes typed tools the agent can call without touching the DB directly
- **Claude agent**: translates natural-language queries into MCP tool calls and synthesizes answers
- **FastAPI**: REST API for external consumers

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Web framework | FastAPI |
| Database | PostgreSQL 16 + pgvector |
| ORM | SQLAlchemy 2 (async) |
| GitHub client | httpx + tenacity |
| AI | Anthropic Claude (claude-sonnet-4-6) |
| MCP | mcp SDK |
| Containerisation | Docker + docker-compose |

## Running locally

```bash
# 1. Copy env template and fill in values
cp .env.example .env

# 2. Start services
docker compose up -d postgres
docker compose up app worker

# 3. Or run the ingestion worker directly
pip install -e ".[dev]"
python -m pulse.ingestion.worker
```

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | Personal access token with `repo` scope |
| `GITHUB_USERNAME` | Yes | Your GitHub username |
| `DATABASE_URL` | Yes | SQLAlchemy connection string |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `GITHUB_REPOS` | No | Comma-separated `owner/repo` list (defaults to all your repos) |

## Design decisions

See [docs/decisions.md](docs/decisions.md).

## Testing

```bash
pytest                  # all tests
pytest -v tests/test_github_client.py   # specific file
```

Tests use SQLite in-memory for DB tests (no Postgres needed) and mock httpx for GitHub client tests.

## What I would do next

- Implement semantic search via pgvector embeddings (Milestone 2)
- Build the full MCP server with search + filter tools (Milestone 3)
- Wire up the Claude agent with tool use (Milestone 4)
- Add a scheduler (APScheduler or cron) to run the worker on a configurable interval
- Add a CLI (`pulse query "..."`) wrapping the agent
- Observability: structured logging, OpenTelemetry traces, Prometheus metrics
- Auth on the FastAPI layer (API key or OAuth)
