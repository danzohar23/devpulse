"""Claude agent — translates natural-language queries into MCP tool calls.

Run as: python -m pulse.agent.agent

Architecture
------------
The agent spawns ``pulse.mcp.server`` as a subprocess and talks to it over
stdio using the MCP Python SDK's client. It does not import the MCP server
module directly (see ADR-014). The agent itself has no DB dependencies.

Per session:
  - Fetch the tool catalogue from the MCP server once (in ``chat``), then
    reuse it for every user turn.

Per turn:
  1. Send the user's question to Claude (claude-sonnet-4-5) along with the
     pre-fetched tools.
  2. While Claude returns a ``tool_use`` stop reason, execute every requested
     tool call via the MCP client, wrap each result in a ``tool_result``
     content block, append it to the conversation, and ask Claude to continue.
  3. When Claude returns ``end_turn``, surface its final text answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from anthropic import AsyncAnthropic
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from pulse.config import settings

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"
_MAX_TOKENS = 4096
_MAX_ITERATIONS = 10  # Safety stop — refuses to spin forever on tool-use loops.

SYSTEM_PROMPT = """You are Pulse, a personal GitHub activity assistant.

You help the user explore *their own* GitHub activity — commits, pull requests, \
and issues — across all of their repositories. The data lives in a private \
database that you can only reach through the tools provided.

Available tools:
- search_activity: semantic search across commits, pull requests, and issues
  by natural-language query.
- get_commits: list recent commits, optionally filtered by repository.
- get_pull_requests: list recent pull requests, optionally filtered by repo
  and state (open / closed).
- get_issues: list recent issues, optionally filtered by repo and state.

Rules:
1. Always use the tools to ground your answers in real data. Never answer
   from memory or general knowledge about what the user's activity *might*
   look like — you cannot see the user's data without calling a tool.
2. If a tool returns no results, say so plainly. Do not guess.
3. Prefer search_activity for open-ended questions ("what did I work on last
   week about authentication?") and the get_* tools for direct listings.
4. Cite the repository name and the URL when referring to a specific commit,
   PR, or issue."""


# ---------------------------------------------------------------------------
# MCP client connection
# ---------------------------------------------------------------------------


@asynccontextmanager
async def mcp_session() -> AsyncIterator[ClientSession]:
    """Spawn the MCP server as a subprocess and yield an initialised client session."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pulse.mcp.server"],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def _mcp_tool_to_anthropic_tool(t: Any) -> dict[str, Any]:
    """Convert an MCP Tool definition to the Anthropic tool schema format."""
    return {
        "name": t.name,
        "description": t.description or "",
        "input_schema": t.inputSchema,
    }


def _extract_text(call_tool_result: Any) -> str:
    """Concatenate the text content of an MCP CallToolResult."""
    parts: list[str] = []
    for content in call_tool_result.content:
        if hasattr(content, "text") and content.text is not None:
            parts.append(content.text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------


async def run_agent_turn(
    user_query: str,
    tools: list[dict[str, Any]],
    anthropic_client: AsyncAnthropic,
    mcp_client: ClientSession,
) -> str:
    """Run a single agent turn: user question in, final text answer out.

    Handles the multi-round tool-use loop. ``tools`` is the pre-fetched and
    pre-converted Anthropic tool catalogue (see ``chat`` for the once-per-
    session fetch). Returns the assistant's final text response once Claude
    stops requesting tools.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_query}]

    for _iteration in range(_MAX_ITERATIONS):
        response = await anthropic_client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

        # No more tools requested → return the final text answer.
        if response.stop_reason != "tool_use" or not tool_use_blocks:
            text_parts = [
                b.text
                for b in response.content
                if getattr(b, "type", None) == "text" and getattr(b, "text", None)
            ]
            return "\n".join(text_parts)

        # Record the assistant's tool_use response so the next turn has context.
        messages.append({"role": "assistant", "content": response.content})

        # Execute each requested tool call and gather tool_result blocks.
        tool_results: list[dict[str, Any]] = []
        for block in tool_use_blocks:
            logger.info("Tool call: %s(%s)", block.name, json.dumps(block.input))
            try:
                result = await mcp_client.call_tool(block.name, block.input)
                result_text = _extract_text(result)
                logger.info(
                    "Tool result for %s: %s%s",
                    block.name,
                    result_text[:200],
                    "…" if len(result_text) > 200 else "",
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — surface any tool error to Claude
                logger.exception("Tool call %s failed", block.name)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    # Loop exhausted — fires exactly once, after the for-loop terminates
    # without an early return. The DEBUG dump of the last message gives
    # something to work with if this ever trips in production.
    logger.warning("Agent loop hit _MAX_ITERATIONS=%d; aborting", _MAX_ITERATIONS)
    logger.debug("Last message at iteration limit: %r", messages[-1] if messages else None)
    return "Sorry — I couldn't complete that request within the tool-use limit."


# ---------------------------------------------------------------------------
# Interactive REPL entry point
# ---------------------------------------------------------------------------


async def chat() -> None:
    """Read questions from stdin, print Claude's answers to stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async with mcp_session() as mcp_client:
        # Fetch the tool catalogue once per session — the server's tool list
        # is fixed at startup, so refetching every turn is pure overhead.
        tools_result = await mcp_client.list_tools()
        tools = [_mcp_tool_to_anthropic_tool(t) for t in tools_result.tools]
        logger.info("Loaded %d tools from the MCP server", len(tools))

        print("Pulse — your GitHub activity assistant. Type 'exit' to quit.")
        while True:
            try:
                user_query = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_query or user_query.lower() in {"exit", "quit"}:
                break
            try:
                answer = await run_agent_turn(user_query, tools, anthropic_client, mcp_client)
            except Exception:
                logger.exception("Agent turn failed")
                print("\nSorry — something went wrong. Check the logs.")
                continue
            print(f"\n{answer}")


if __name__ == "__main__":
    asyncio.run(chat())
