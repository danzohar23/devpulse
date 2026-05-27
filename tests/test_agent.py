"""Tests for the Claude agent's tool-use loop.

The MCP client and Anthropic client are both mocked. The agent's loop is
driven by feeding sequences of fake Anthropic responses and asserting the
tool calls / message shapes that result.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pulse.agent.agent import (
    _extract_text,
    _mcp_tool_to_anthropic_tool,
    run_agent_turn,
)

# ---------------------------------------------------------------------------
# Block / response helpers
# ---------------------------------------------------------------------------


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(name: str, input_: dict, id_: str = "toolu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id_)


def _claude_response(content: list, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=content, stop_reason=stop_reason)


def _mcp_text_content(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)


def _mcp_call_result(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[_mcp_text_content(text)])


def _mcp_tool(
    name: str = "get_commits",
    description: str = "Recent commits",
    schema: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema=schema or {"type": "object", "properties": {}},
    )


def _make_clients(
    *,
    claude_responses: list,
    mcp_call_results: list | None = None,
) -> tuple[Any, Any]:
    """Build matching mock anthropic_client and mcp_client pairs.

    Note: ``list_tools`` is mocked but should *never* be called from
    ``run_agent_turn`` — the tool catalogue is now passed in as an argument
    (fetched once per session in ``chat``).
    """
    mcp_client = MagicMock()
    mcp_client.list_tools = AsyncMock(return_value=SimpleNamespace(tools=[]))
    if mcp_call_results is None:
        mcp_client.call_tool = AsyncMock()
    else:
        mcp_client.call_tool = AsyncMock(side_effect=mcp_call_results)

    anthropic_client = MagicMock()
    anthropic_client.messages = MagicMock()
    anthropic_client.messages.create = AsyncMock(side_effect=claude_responses)

    return anthropic_client, mcp_client


# Pre-converted Anthropic tool catalogue used by most tests. Mirrors what
# chat() would produce from the MCP server's list_tools result.
_DEFAULT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_commits",
        "description": "Recent commits",
        "input_schema": {"type": "object", "properties": {}},
    }
]


# ---------------------------------------------------------------------------
# _mcp_tool_to_anthropic_tool — schema conversion
# ---------------------------------------------------------------------------


def test_mcp_tool_to_anthropic_tool_renames_input_schema() -> None:
    mcp = _mcp_tool(
        name="search_activity",
        description="Semantic search",
        schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    converted = _mcp_tool_to_anthropic_tool(mcp)
    assert converted == {
        "name": "search_activity",
        "description": "Semantic search",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    }


def test_mcp_tool_to_anthropic_tool_handles_none_description() -> None:
    mcp = SimpleNamespace(name="x", description=None, inputSchema={"type": "object"})
    converted = _mcp_tool_to_anthropic_tool(mcp)
    assert converted["description"] == ""


def test_extract_text_joins_multiple_blocks() -> None:
    result = SimpleNamespace(
        content=[_mcp_text_content("first"), _mcp_text_content("second")]
    )
    assert _extract_text(result) == "first\nsecond"


# ---------------------------------------------------------------------------
# Loop behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tool_call_returns_text_and_exits() -> None:
    """When Claude returns end_turn with text only, the loop exits immediately."""
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[
            _claude_response([_text_block("hello there")], stop_reason="end_turn"),
        ],
    )

    result = await run_agent_turn("hi", _DEFAULT_TOOLS, anthropic_client, mcp_client)

    assert result == "hello there"
    mcp_client.call_tool.assert_not_called()
    assert anthropic_client.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_tool_use_block_is_routed_to_mcp_client() -> None:
    """A tool_use block from Claude is dispatched to mcp_client.call_tool."""
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[
            _claude_response(
                [_tool_use_block("get_commits", {"limit": 5})],
                stop_reason="tool_use",
            ),
            _claude_response([_text_block("Found 1 commit.")], stop_reason="end_turn"),
        ],
        mcp_call_results=[_mcp_call_result('[{"sha":"abc"}]')],
    )

    result = await run_agent_turn(
        "show me commits", _DEFAULT_TOOLS, anthropic_client, mcp_client
    )

    assert result == "Found 1 commit."
    mcp_client.call_tool.assert_called_once_with("get_commits", {"limit": 5})


@pytest.mark.asyncio
async def test_tool_result_is_passed_back_to_claude() -> None:
    """The next Claude call must include the MCP output as a tool_result block."""
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[
            _claude_response(
                [_tool_use_block("get_commits", {}, id_="toolu_42")],
                stop_reason="tool_use",
            ),
            _claude_response([_text_block("Done.")], stop_reason="end_turn"),
        ],
        mcp_call_results=[_mcp_call_result('[{"sha":"abc"}]')],
    )

    await run_agent_turn("show me commits", _DEFAULT_TOOLS, anthropic_client, mcp_client)

    # Inspect the messages payload of the *second* Anthropic call.
    second_call = anthropic_client.messages.create.call_args_list[1]
    second_messages = second_call.kwargs["messages"]

    # Should be: [user, assistant (tool_use), user (tool_result)]
    assert len(second_messages) == 3
    assert second_messages[0]["role"] == "user"
    assert second_messages[1]["role"] == "assistant"

    tool_result_msg = second_messages[2]
    assert tool_result_msg["role"] == "user"
    assert isinstance(tool_result_msg["content"], list)

    tool_result_block = tool_result_msg["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert tool_result_block["tool_use_id"] == "toolu_42"
    assert tool_result_block["content"] == '[{"sha":"abc"}]'


@pytest.mark.asyncio
async def test_tools_argument_is_forwarded_to_claude() -> None:
    """The pre-converted tool catalogue passed in is forwarded verbatim to Claude."""
    tools: list[dict[str, Any]] = [
        {
            "name": "search_activity",
            "description": "Semantic search",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }
    ]
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[_claude_response([_text_block("ok")], stop_reason="end_turn")],
    )

    await run_agent_turn("hello", tools, anthropic_client, mcp_client)

    sent_tools = anthropic_client.messages.create.call_args.kwargs["tools"]
    assert sent_tools == tools


@pytest.mark.asyncio
async def test_multiple_tool_use_rounds() -> None:
    """The loop handles several rounds of tool calls before a final text response."""
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[
            _claude_response(
                [_tool_use_block("get_commits", {}, id_="t1")],
                stop_reason="tool_use",
            ),
            _claude_response(
                [_tool_use_block("get_issues", {}, id_="t2")],
                stop_reason="tool_use",
            ),
            _claude_response([_text_block("Summary done.")], stop_reason="end_turn"),
        ],
        mcp_call_results=[
            _mcp_call_result("commits-payload"),
            _mcp_call_result("issues-payload"),
        ],
    )

    result = await run_agent_turn("summarise", _DEFAULT_TOOLS, anthropic_client, mcp_client)

    assert result == "Summary done."
    assert mcp_client.call_tool.call_count == 2
    assert anthropic_client.messages.create.call_count == 3

    # Each call_tool invocation routed to the right MCP tool name.
    first_call, second_call = mcp_client.call_tool.call_args_list
    assert first_call.args[0] == "get_commits"
    assert second_call.args[0] == "get_issues"


@pytest.mark.asyncio
async def test_parallel_tool_calls_in_one_response() -> None:
    """Two tool_use blocks in a single Claude response → two MCP calls, two tool_results."""
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[
            _claude_response(
                [
                    _tool_use_block("get_commits", {}, id_="t1"),
                    _tool_use_block("get_issues", {}, id_="t2"),
                ],
                stop_reason="tool_use",
            ),
            _claude_response([_text_block("Done.")], stop_reason="end_turn"),
        ],
        mcp_call_results=[_mcp_call_result("c-out"), _mcp_call_result("i-out")],
    )

    await run_agent_turn("multi", _DEFAULT_TOOLS, anthropic_client, mcp_client)

    assert mcp_client.call_tool.call_count == 2
    second_messages = anthropic_client.messages.create.call_args_list[1].kwargs["messages"]
    tool_results = second_messages[2]["content"]
    assert len(tool_results) == 2
    assert {tr["tool_use_id"] for tr in tool_results} == {"t1", "t2"}


@pytest.mark.asyncio
async def test_tool_call_failure_returned_as_is_error() -> None:
    """If the MCP call raises, a tool_result with is_error=True is sent back."""
    mcp_client = MagicMock()
    mcp_client.list_tools = AsyncMock(return_value=SimpleNamespace(tools=[_mcp_tool()]))
    mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("boom"))

    anthropic_client = MagicMock()
    anthropic_client.messages = MagicMock()
    anthropic_client.messages.create = AsyncMock(
        side_effect=[
            _claude_response(
                [_tool_use_block("get_commits", {}, id_="t1")],
                stop_reason="tool_use",
            ),
            _claude_response([_text_block("recovered")], stop_reason="end_turn"),
        ]
    )

    result = await run_agent_turn("try", _DEFAULT_TOOLS, anthropic_client, mcp_client)

    assert result == "recovered"
    second_messages = anthropic_client.messages.create.call_args_list[1].kwargs["messages"]
    tool_result_block = second_messages[2]["content"][0]
    assert tool_result_block.get("is_error") is True
    assert "boom" in tool_result_block["content"]


@pytest.mark.asyncio
async def test_logs_tool_calls_at_info_level(caplog: pytest.LogCaptureFixture) -> None:
    """Every tool call and its result are logged at INFO."""
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[
            _claude_response(
                [_tool_use_block("get_commits", {"limit": 3}, id_="t1")],
                stop_reason="tool_use",
            ),
            _claude_response([_text_block("ok")], stop_reason="end_turn"),
        ],
        mcp_call_results=[_mcp_call_result("payload")],
    )

    with caplog.at_level("INFO", logger="pulse.agent.agent"):
        await run_agent_turn("hi", _DEFAULT_TOOLS, anthropic_client, mcp_client)

    log_text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "Tool call: get_commits" in log_text
    assert "Tool result for get_commits" in log_text


# ---------------------------------------------------------------------------
# Tool catalogue is fetched in chat(), not in run_agent_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_agent_turn_does_not_call_list_tools() -> None:
    """run_agent_turn must not refetch the catalogue — chat() does it once per session."""
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[_claude_response([_text_block("ok")], stop_reason="end_turn")],
    )

    await run_agent_turn("hi", _DEFAULT_TOOLS, anthropic_client, mcp_client)

    mcp_client.list_tools.assert_not_called()


@pytest.mark.asyncio
async def test_list_tools_not_called_across_multiple_turns() -> None:
    """Across N turns in the same session, list_tools fires zero times from the loop."""
    anthropic_client, mcp_client = _make_clients(
        claude_responses=[
            _claude_response([_text_block("first")], stop_reason="end_turn"),
            _claude_response([_text_block("second")], stop_reason="end_turn"),
            _claude_response([_text_block("third")], stop_reason="end_turn"),
        ],
    )

    await run_agent_turn("q1", _DEFAULT_TOOLS, anthropic_client, mcp_client)
    await run_agent_turn("q2", _DEFAULT_TOOLS, anthropic_client, mcp_client)
    await run_agent_turn("q3", _DEFAULT_TOOLS, anthropic_client, mcp_client)

    mcp_client.list_tools.assert_not_called()
    # Each turn still hits Claude exactly once (no tool_use → end_turn)
    assert anthropic_client.messages.create.call_count == 3
