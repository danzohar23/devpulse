"""MCP server — exposes GitHub activity data as typed tools for the agent.

Run as: python -m pulse.mcp.server

Tools registered:
    search_activity  — embed a free-text query and call search_similar
    get_commits      — recent commits, optional repo filter
    get_pull_requests — recent PRs, optional repo / state filters
    get_issues       — recent issues, optional repo / state filters

All tools call the repository layer exclusively; no module outside
db/repository.py touches the database directly (ADR-001).
"""

from __future__ import annotations

import asyncio
import json
import logging

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from sqlalchemy.ext.asyncio import AsyncSession

from pulse.db.engine import get_session
from pulse.db.repository import (
    get_recent_commits,
    get_recent_issues,
    get_recent_pull_requests,
    search_similar,
)
from pulse.indexing.embedder import embed_texts

logger = logging.getLogger(__name__)

_server = Server("pulse")


# ---------------------------------------------------------------------------
# Business-logic functions — call the repository layer, return list[dict].
# Defined at module level so tests can call them directly without going
# through the MCP wire protocol.
# ---------------------------------------------------------------------------


async def tool_search_activity(
    session: AsyncSession,
    query: str,
    repo: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Embed *query* and return the most semantically similar activity records."""
    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(None, embed_texts, [query])
    results = await search_similar(session, embeddings[0], limit=limit, repo=repo)
    return [r.model_dump(mode="json") for r in results]


async def tool_get_commits(
    session: AsyncSession,
    repo: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return recent commits, optionally filtered by *repo*."""
    commits = await get_recent_commits(session, repo=repo, limit=limit)
    return [c.model_dump(mode="json") for c in commits]


async def tool_get_pull_requests(
    session: AsyncSession,
    repo: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return recent pull requests, optionally filtered by *repo* and *state*."""
    prs = await get_recent_pull_requests(session, repo=repo, state=state, limit=limit)
    return [pr.model_dump(mode="json") for pr in prs]


async def tool_get_issues(
    session: AsyncSession,
    repo: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return recent issues, optionally filtered by *repo* and *state*."""
    issues = await get_recent_issues(session, repo=repo, state=state, limit=limit)
    return [i.model_dump(mode="json") for i in issues]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


@_server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_activity",
            description=(
                "Semantic search across commits, pull requests, and issues "
                "using a natural-language query. Requires PostgreSQL with pgvector."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Restrict results to this repository (owner/name)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of results to return",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_commits",
            description="Return recent commits, optionally filtered by repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Filter to this repository (owner/name)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Maximum number of commits to return (1–200)",
                    },
                },
            },
        ),
        types.Tool(
            name="get_pull_requests",
            description=(
                "Return recent pull requests, optionally filtered by repository and state."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Filter to this repository (owner/name)",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed"],
                        "description": "Filter by pull request state",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Maximum number of pull requests to return (1–200)",
                    },
                },
            },
        ),
        types.Tool(
            name="get_issues",
            description=(
                "Return recent issues, optionally filtered by repository and state."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Filter to this repository (owner/name)",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed"],
                        "description": "Filter by issue state",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Maximum number of issues to return (1–200)",
                    },
                },
            },
        ),
    ]


def _clamp_limit(raw: object, default: int) -> int:
    """Parse and clamp a raw limit value to [1, 200]."""
    return max(1, min(200, int(raw if raw is not None else default)))


@_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Trace breadcrumbs — useful when the agent subprocess appears to hang.
    # Each line tells us which await we got past.
    logger.info("call_tool invoked: name=%s arguments=%s", name, arguments)
    try:
        async with get_session() as session:
            logger.info("call_tool %s: DB session opened", name)
            if name == "search_activity":
                limit = _clamp_limit(arguments.get("limit"), 10)
                result = await tool_search_activity(
                    session,
                    query=arguments["query"],
                    repo=arguments.get("repo"),
                    limit=limit,
                )
            elif name == "get_commits":
                limit = _clamp_limit(arguments.get("limit"), 50)
                result = await tool_get_commits(
                    session,
                    repo=arguments.get("repo"),
                    limit=limit,
                )
            elif name == "get_pull_requests":
                limit = _clamp_limit(arguments.get("limit"), 50)
                result = await tool_get_pull_requests(
                    session,
                    repo=arguments.get("repo"),
                    state=arguments.get("state"),
                    limit=limit,
                )
            elif name == "get_issues":
                limit = _clamp_limit(arguments.get("limit"), 50)
                result = await tool_get_issues(
                    session,
                    repo=arguments.get("repo"),
                    state=arguments.get("state"),
                    limit=limit,
                )
            else:
                raise ValueError(f"Unknown tool: {name!r}")
        logger.info(
            "call_tool %s: tool returned %d row(s); serialising response",
            name,
            len(result),
        )
    except NotImplementedError:
        return [
            types.TextContent(
                type="text",
                text="Error: this tool requires PostgreSQL with pgvector",
            )
        ]
    except Exception:
        logger.exception("Unhandled error in call_tool for %r", name)
        return [types.TextContent(type="text", text="Error: internal server error")]

    return [types.TextContent(type="text", text=json.dumps(result))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await _server.run(
            read_stream,
            write_stream,
            _server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_run())
