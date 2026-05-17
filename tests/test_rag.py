"""Tests for the RAG pipeline: embedder, repository embedding functions, and indexer."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pulse.db.repository import (
    get_unindexed_commits,
    get_unindexed_issues,
    get_unindexed_pull_requests,
    search_similar,
    set_commit_embedding,
    set_issue_embedding,
    set_pull_request_embedding,
    upsert_commit,
    upsert_issue,
    upsert_pull_request,
)
from pulse.indexing.embedder import embed_texts
from pulse.indexing.indexer import run_indexing
from pulse.models import EMBEDDING_DIM, Commit, Issue, PullRequest

_TS = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
_FAKE_VEC = [0.1] * EMBEDDING_DIM


# ---------------------------------------------------------------------------
# Helpers
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


def _pr(pr_id: int = 1, repo: str = "owner/repo") -> PullRequest:
    return PullRequest(
        pr_id=pr_id,
        repo=repo,
        title="Add thing",
        body="Detailed description.",
        state="open",
        merged_at=None,
        created_at=_TS,
        url=f"https://github.com/{repo}/pull/{pr_id}",
    )


def _issue(issue_id: int = 1, repo: str = "owner/repo") -> Issue:
    return Issue(
        issue_id=issue_id,
        repo=repo,
        title="Bug report",
        body="Something broke.",
        state="open",
        created_at=_TS,
        closed_at=None,
        url=f"https://github.com/{repo}/issues/{issue_id}",
    )


def _make_openai_response(texts: list[str]) -> Any:
    """Build a mock openai.types.CreateEmbeddingResponse for the given texts."""
    mock_resp = MagicMock()
    mock_resp.data = [
        MagicMock(index=i, embedding=_FAKE_VEC) for i in range(len(texts))
    ]
    return mock_resp


# ---------------------------------------------------------------------------
# embedder tests
# ---------------------------------------------------------------------------


class TestEmbedTexts:
    def test_returns_one_vector_per_text(self) -> None:
        texts = ["hello", "world", "foo"]
        with patch("pulse.indexing.embedder.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.embeddings.create.return_value = _make_openai_response(texts)
            result = embed_texts(texts)

        assert len(result) == 3
        assert all(len(v) == EMBEDDING_DIM for v in result)

    def test_empty_input_returns_empty_without_api_call(self) -> None:
        with patch("pulse.indexing.embedder.OpenAI") as MockOpenAI:
            result = embed_texts([])

        MockOpenAI.assert_not_called()
        assert result == []

    def test_batches_large_input(self) -> None:
        # 250 texts should produce 3 API calls with batch size 100
        texts = [f"text {i}" for i in range(250)]
        create_mock = MagicMock(side_effect=lambda **kw: _make_openai_response(kw["input"]))

        with patch("pulse.indexing.embedder.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.embeddings.create = create_mock
            result = embed_texts(texts)

        assert create_mock.call_count == 3
        assert len(result) == 250

    def test_batch_boundaries_are_correct(self) -> None:
        texts = [f"t{i}" for i in range(150)]
        batches_seen: list[list[str]] = []

        def capture(**kw: Any) -> Any:
            batches_seen.append(kw["input"])
            return _make_openai_response(kw["input"])

        with patch("pulse.indexing.embedder.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.embeddings.create = MagicMock(side_effect=capture)
            embed_texts(texts)

        assert len(batches_seen) == 2
        assert len(batches_seen[0]) == 100
        assert len(batches_seen[1]) == 50


# ---------------------------------------------------------------------------
# Repository embedding write/read tests (SQLite in-memory)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_commit_embedding_stored_and_retrieved(db_session: AsyncSession) -> None:
    commit = _commit()
    await upsert_commit(db_session, commit)
    await db_session.commit()

    await set_commit_embedding(db_session, commit.sha, _FAKE_VEC)
    await db_session.commit()

    from sqlalchemy import select

    from pulse.models import CommitRecord

    row = await db_session.scalar(
        select(CommitRecord).where(CommitRecord.sha == commit.sha)
    )
    assert row is not None
    assert row.embedding is not None
    assert len(row.embedding) == EMBEDDING_DIM


@pytest.mark.asyncio
async def test_set_pr_embedding_stored_and_retrieved(db_session: AsyncSession) -> None:
    pr = _pr()
    await upsert_pull_request(db_session, pr)
    await db_session.commit()

    await set_pull_request_embedding(db_session, pr.pr_id, pr.repo, _FAKE_VEC)
    await db_session.commit()

    from sqlalchemy import select

    from pulse.models import PullRequestRecord

    row = await db_session.scalar(
        select(PullRequestRecord).where(
            PullRequestRecord.pr_id == pr.pr_id,
            PullRequestRecord.repo == pr.repo,
        )
    )
    assert row is not None
    assert row.embedding is not None
    assert len(row.embedding) == EMBEDDING_DIM


@pytest.mark.asyncio
async def test_set_issue_embedding_stored_and_retrieved(db_session: AsyncSession) -> None:
    issue = _issue()
    await upsert_issue(db_session, issue)
    await db_session.commit()

    await set_issue_embedding(db_session, issue.issue_id, issue.repo, _FAKE_VEC)
    await db_session.commit()

    from sqlalchemy import select

    from pulse.models import IssueRecord

    row = await db_session.scalar(
        select(IssueRecord).where(
            IssueRecord.issue_id == issue.issue_id,
            IssueRecord.repo == issue.repo,
        )
    )
    assert row is not None
    assert row.embedding is not None
    assert len(row.embedding) == EMBEDDING_DIM


# ---------------------------------------------------------------------------
# get_unindexed_* tests (SQLite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_unindexed_commits_returns_only_null_embedding(
    db_session: AsyncSession,
) -> None:
    c1 = _commit("sha1")
    c2 = _commit("sha2")
    await upsert_commit(db_session, c1)
    await upsert_commit(db_session, c2)
    await db_session.commit()

    # Give c1 an embedding
    await set_commit_embedding(db_session, c1.sha, _FAKE_VEC)
    await db_session.commit()

    unindexed = await get_unindexed_commits(db_session)
    assert len(unindexed) == 1
    assert unindexed[0].sha == "sha2"


@pytest.mark.asyncio
async def test_get_unindexed_commits_batch_size_respected(db_session: AsyncSession) -> None:
    for i in range(5):
        await upsert_commit(db_session, _commit(f"sha{i}"))
    await db_session.commit()

    unindexed = await get_unindexed_commits(db_session, batch_size=3)
    assert len(unindexed) == 3


@pytest.mark.asyncio
async def test_get_unindexed_pull_requests_returns_only_null_embedding(
    db_session: AsyncSession,
) -> None:
    pr1 = _pr(pr_id=1)
    pr2 = _pr(pr_id=2)
    await upsert_pull_request(db_session, pr1)
    await upsert_pull_request(db_session, pr2)
    await db_session.commit()

    await set_pull_request_embedding(db_session, pr1.pr_id, pr1.repo, _FAKE_VEC)
    await db_session.commit()

    unindexed = await get_unindexed_pull_requests(db_session)
    assert len(unindexed) == 1
    assert unindexed[0].pr_id == 2


@pytest.mark.asyncio
async def test_get_unindexed_issues_returns_only_null_embedding(
    db_session: AsyncSession,
) -> None:
    i1 = _issue(issue_id=1)
    i2 = _issue(issue_id=2)
    await upsert_issue(db_session, i1)
    await upsert_issue(db_session, i2)
    await db_session.commit()

    await set_issue_embedding(db_session, i1.issue_id, i1.repo, _FAKE_VEC)
    await db_session.commit()

    unindexed = await get_unindexed_issues(db_session)
    assert len(unindexed) == 1
    assert unindexed[0].issue_id == 2


# ---------------------------------------------------------------------------
# search_similar — returns [] on SQLite (pgvector operators unavailable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_similar_returns_empty_on_sqlite(db_session: AsyncSession) -> None:
    results = await search_similar(db_session, _FAKE_VEC, limit=5)
    assert results == []


# ---------------------------------------------------------------------------
# Indexer integration test (mocked embedder, SQLite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_indexing_embeds_all_records(db_session: AsyncSession) -> None:
    """Indexer loops until every unindexed record has been processed."""
    # Seed 2 commits, 1 PR, 1 issue — all without embeddings
    await upsert_commit(db_session, _commit("sha1"))
    await upsert_commit(db_session, _commit("sha2"))
    await upsert_pull_request(db_session, _pr(pr_id=10))
    await upsert_issue(db_session, _issue(issue_id=20))
    await db_session.commit()

    call_count = 0

    def fake_embed(texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        return [_FAKE_VEC for _ in texts]

    from contextlib import asynccontextmanager

    # side_effect (not return_value) so a *fresh* context manager is returned
    # on every get_session() call — a single CM instance can only be entered once.
    def make_ctx() -> Any:
        @asynccontextmanager
        async def _ctx():  # type: ignore[return]
            yield db_session
        return _ctx()

    with (
        patch("pulse.indexing.indexer.embed_texts", side_effect=fake_embed),
        patch("pulse.indexing.indexer.get_session", side_effect=make_ctx),
    ):
        await run_indexing(batch_size=10)

    # embed_texts must have been called at least once per entity type that had
    # unindexed records (commits, PR, issue)
    assert call_count >= 3


@pytest.mark.asyncio
async def test_run_indexing_skips_already_indexed_records(db_session: AsyncSession) -> None:
    commit = _commit("already_indexed")
    await upsert_commit(db_session, commit)
    await set_commit_embedding(db_session, commit.sha, _FAKE_VEC)
    await db_session.commit()

    from contextlib import asynccontextmanager

    def make_ctx() -> Any:
        @asynccontextmanager
        async def _ctx():  # type: ignore[return]
            yield db_session
        return _ctx()

    with (
        patch("pulse.indexing.indexer.embed_texts") as mock_embed,
        patch("pulse.indexing.indexer.get_session", side_effect=make_ctx),
    ):
        await run_indexing(batch_size=10)

    # No texts to embed — embed_texts should never have been called
    mock_embed.assert_not_called()
