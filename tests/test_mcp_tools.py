"""Tests for the MCP server tool-logic functions (Milestone 3).

All four tool functions are tested directly (bypassing the MCP wire protocol)
so tests stay fast and don't require a running server process.

search_activity mocks both embed_texts and search_similar because:
  - embed_texts would call the real OpenAI API
  - search_similar raises NotImplementedError on SQLite (ADR-013)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pulse.db.repository import (
    upsert_commit,
    upsert_issue,
    upsert_pull_request,
)
from pulse.mcp.server import (
    call_tool,
    tool_get_commits,
    tool_get_issues,
    tool_get_pull_requests,
    tool_search_activity,
)
from pulse.models import EMBEDDING_DIM, Commit, Issue, PullRequest, SearchResult

_TS = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
_FAKE_VEC = [0.1] * EMBEDDING_DIM


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def _commit(sha: str = "abc123", repo: str = "owner/repo") -> Commit:
    return Commit(
        sha=sha,
        repo=repo,
        message="feat: add thing",
        author_name="Dev",
        author_email="dev@example.com",
        timestamp=_TS,
        url=f"https://github.com/{repo}/commit/{sha}",
    )


def _pr(pr_id: int = 1, repo: str = "owner/repo", state: str = "open") -> PullRequest:
    return PullRequest(
        pr_id=pr_id,
        repo=repo,
        title="Add feature",
        body="Body text.",
        state=state,
        merged_at=None,
        created_at=_TS,
        url=f"https://github.com/{repo}/pull/{pr_id}",
    )


def _issue(issue_id: int = 7, repo: str = "owner/repo", state: str = "open") -> Issue:
    return Issue(
        issue_id=issue_id,
        repo=repo,
        title="Bug report",
        body="Description.",
        state=state,
        created_at=_TS,
        closed_at=None,
        url=f"https://github.com/{repo}/issues/{issue_id}",
    )


def _search_result(title: str = "feat: add thing") -> SearchResult:
    return SearchResult(
        type="commit",
        score=0.95,
        repo="owner/repo",
        url="https://github.com/owner/repo/commit/abc",
        title=title,
        body=None,
        state=None,
        created_at=_TS,
    )


# ---------------------------------------------------------------------------
# tool_get_commits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_get_commits_returns_seeded_data(db_session: AsyncSession) -> None:
    await upsert_commit(db_session, _commit("sha1"))
    await upsert_commit(db_session, _commit("sha2"))
    await db_session.commit()

    result = await tool_get_commits(db_session)

    assert len(result) == 2
    shas = {r["sha"] for r in result}
    assert shas == {"sha1", "sha2"}


@pytest.mark.asyncio
async def test_tool_get_commits_repo_filter(db_session: AsyncSession) -> None:
    await upsert_commit(db_session, _commit("sha1", repo="owner/alpha"))
    await upsert_commit(db_session, _commit("sha2", repo="owner/beta"))
    await db_session.commit()

    result = await tool_get_commits(db_session, repo="owner/alpha")

    assert len(result) == 1
    assert result[0]["sha"] == "sha1"


@pytest.mark.asyncio
async def test_tool_get_commits_limit(db_session: AsyncSession) -> None:
    for i in range(5):
        await upsert_commit(db_session, _commit(f"sha{i}"))
    await db_session.commit()

    result = await tool_get_commits(db_session, limit=3)

    assert len(result) == 3


@pytest.mark.asyncio
async def test_tool_get_commits_returns_dicts(db_session: AsyncSession) -> None:
    await upsert_commit(db_session, _commit("sha1"))
    await db_session.commit()

    result = await tool_get_commits(db_session)

    assert isinstance(result, list)
    assert isinstance(result[0], dict)
    assert "sha" in result[0]
    assert "repo" in result[0]
    assert "message" in result[0]


# ---------------------------------------------------------------------------
# tool_get_pull_requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_get_pull_requests_returns_seeded_data(db_session: AsyncSession) -> None:
    await upsert_pull_request(db_session, _pr(1))
    await upsert_pull_request(db_session, _pr(2))
    await db_session.commit()

    result = await tool_get_pull_requests(db_session)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_tool_get_pull_requests_state_filter(db_session: AsyncSession) -> None:
    await upsert_pull_request(db_session, _pr(1, state="open"))
    await upsert_pull_request(db_session, _pr(2, state="closed"))
    await db_session.commit()

    open_prs = await tool_get_pull_requests(db_session, state="open")
    closed_prs = await tool_get_pull_requests(db_session, state="closed")

    assert len(open_prs) == 1
    assert open_prs[0]["state"] == "open"
    assert len(closed_prs) == 1
    assert closed_prs[0]["state"] == "closed"


@pytest.mark.asyncio
async def test_tool_get_pull_requests_repo_filter(db_session: AsyncSession) -> None:
    await upsert_pull_request(db_session, _pr(1, repo="owner/alpha"))
    await upsert_pull_request(db_session, _pr(2, repo="owner/beta"))
    await db_session.commit()

    result = await tool_get_pull_requests(db_session, repo="owner/beta")

    assert len(result) == 1
    assert result[0]["pr_id"] == 2


@pytest.mark.asyncio
async def test_tool_get_pull_requests_returns_dicts(db_session: AsyncSession) -> None:
    await upsert_pull_request(db_session, _pr(1))
    await db_session.commit()

    result = await tool_get_pull_requests(db_session)

    assert isinstance(result[0], dict)
    assert "pr_id" in result[0]
    assert "state" in result[0]


# ---------------------------------------------------------------------------
# tool_get_issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_get_issues_returns_seeded_data(db_session: AsyncSession) -> None:
    await upsert_issue(db_session, _issue(1))
    await upsert_issue(db_session, _issue(2))
    await db_session.commit()

    result = await tool_get_issues(db_session)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_tool_get_issues_state_filter(db_session: AsyncSession) -> None:
    await upsert_issue(db_session, _issue(1, state="open"))
    await upsert_issue(db_session, _issue(2, state="closed"))
    await db_session.commit()

    open_issues = await tool_get_issues(db_session, state="open")
    closed_issues = await tool_get_issues(db_session, state="closed")

    assert len(open_issues) == 1
    assert open_issues[0]["state"] == "open"
    assert len(closed_issues) == 1
    assert closed_issues[0]["state"] == "closed"


@pytest.mark.asyncio
async def test_tool_get_issues_repo_filter(db_session: AsyncSession) -> None:
    await upsert_issue(db_session, _issue(1, repo="owner/alpha"))
    await upsert_issue(db_session, _issue(2, repo="owner/beta"))
    await db_session.commit()

    result = await tool_get_issues(db_session, repo="owner/alpha")

    assert len(result) == 1
    assert result[0]["issue_id"] == 1


@pytest.mark.asyncio
async def test_tool_get_issues_returns_dicts(db_session: AsyncSession) -> None:
    await upsert_issue(db_session, _issue(7))
    await db_session.commit()

    result = await tool_get_issues(db_session)

    assert isinstance(result[0], dict)
    assert "issue_id" in result[0]
    assert "state" in result[0]


# ---------------------------------------------------------------------------
# tool_search_activity — mocked (search_similar raises NotImplementedError
# on SQLite; embed_texts would call the real OpenAI API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_search_activity_returns_results(db_session: AsyncSession) -> None:
    """search_activity embeds the query and returns serialised SearchResults."""
    fake_results = [_search_result("feat: add thing"), _search_result("fix: resolve bug")]

    with (
        patch("pulse.mcp.server.embed_texts", return_value=[_FAKE_VEC]),
        patch(
            "pulse.mcp.server.search_similar",
            new_callable=AsyncMock,
            return_value=fake_results,
        ),
    ):
        result = await tool_search_activity(db_session, query="recent feature work", limit=5)

    assert len(result) == 2
    assert result[0]["type"] == "commit"
    assert result[0]["score"] == 0.95


@pytest.mark.asyncio
async def test_tool_search_activity_passes_repo_filter(db_session: AsyncSession) -> None:
    """The repo argument is forwarded to search_similar."""
    mock_search = AsyncMock(return_value=[])

    with (
        patch("pulse.mcp.server.embed_texts", return_value=[_FAKE_VEC]),
        patch("pulse.mcp.server.search_similar", mock_search),
    ):
        await tool_search_activity(db_session, query="bug", repo="owner/repo", limit=3)

    mock_search.assert_called_once_with(db_session, _FAKE_VEC, limit=3, repo="owner/repo")


@pytest.mark.asyncio
async def test_tool_search_activity_embeds_query(db_session: AsyncSession) -> None:
    """embed_texts is called exactly once with the user's query string."""
    with (
        patch("pulse.mcp.server.embed_texts", return_value=[_FAKE_VEC]) as embed_spy,
        patch(
            "pulse.mcp.server.search_similar",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await tool_search_activity(db_session, query="my search query")

    embed_spy.assert_called_once_with(["my search query"])


@pytest.mark.asyncio
async def test_tool_search_activity_returns_dicts(db_session: AsyncSession) -> None:
    """Results are plain dicts, not SearchResult objects."""
    with (
        patch("pulse.mcp.server.embed_texts", return_value=[_FAKE_VEC]),
        patch(
            "pulse.mcp.server.search_similar",
            new_callable=AsyncMock,
            return_value=[_search_result()],
        ),
    ):
        result = await tool_search_activity(db_session, query="anything")

    assert isinstance(result, list)
    assert isinstance(result[0], dict)
    assert "type" in result[0]
    assert "score" in result[0]
    assert "repo" in result[0]
    assert "url" in result[0]


# ---------------------------------------------------------------------------
# call_tool error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_returns_error_text_on_not_implemented() -> None:
    """call_tool catches NotImplementedError from search_activity_asyncpg and returns an error TextContent.

    This exercises the pgvector-unavailable path that real callers would hit when
    pgvector is not installed on the PostgreSQL server (ADR-013).
    """
    from unittest.mock import MagicMock

    mock_pool = MagicMock()

    with (
        patch("pulse.mcp.server.embed_texts", return_value=[_FAKE_VEC]),
        patch("pulse.mcp.server.get_asyncpg_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch(
            "pulse.mcp.server.search_activity_asyncpg",
            new_callable=AsyncMock,
            side_effect=NotImplementedError("search_activity requires PostgreSQL with pgvector"),
        ),
    ):
        response = await call_tool("search_activity", {"query": "test"})

    assert len(response) == 1
    assert "Error" in response[0].text
    assert "PostgreSQL" in response[0].text
    # Must not be the generic internal-error message
    assert "internal server error" not in response[0].text
