"""Claude agent — translates natural-language queries into MCP tool calls.

TODO (Milestone 4):
- Initialise anthropic.Anthropic client
- Send user query + tool definitions (from MCP server) to claude-sonnet-4-6
- Run the tool-use loop: model picks tool → execute via MCP → feed result back
- Stream the final answer to the caller
- Expose: async def query(text: str) -> AsyncIterator[str]
"""

from __future__ import annotations


async def query(text: str) -> str:  # noqa: ARG001
    raise NotImplementedError("Agent not yet implemented (Milestone 4)")
