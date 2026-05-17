"""MCP server — exposes GitHub activity data as typed tools for the agent.

TODO (Milestone 3):
- Initialise an mcp.Server instance
- Register tools:
    search_activity(query: str, since: str, repo: str | None) -> list[dict]
    get_commits(repo: str, limit: int) -> list[dict]
    get_pull_requests(repo: str, state: str, limit: int) -> list[dict]
    get_issues(repo: str, state: str, limit: int) -> list[dict]
- Each tool calls the repository layer (never the DB directly)
- Run server via stdio transport for use with Claude Desktop / agent
"""

from __future__ import annotations
