"""Tests for the FastAPI layer (Milestone 2)."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pulse.api.dependencies import get_db_session
from pulse.api.main import app
from pulse.db import repository
from pulse.models import Base, Commit, Issue, PullRequest

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def api_client() -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient wired to an in-memory SQLite DB via dependency override."""
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = _override_session
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._session_factory = SessionLocal  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed(client: AsyncClient, *items: Commit | PullRequest | Issue) -> None:
    """Insert items through repository functions into the test DB."""
    factory: async_sessionmaker[AsyncSession] = client._session_factory  # type: ignore[attr-defined]
    async with factory() as session:
        for item in items:
            if isinstance(item, Commit):
                await repository.upsert_commit(session, item)
            elif isinstance(item, PullRequest):
                await repository.upsert_pull_request(session, item)
            elif isinstance(item, Issue):
                await repository.upsert_issue(session, item)
        await session.commit()


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

def _commit(sha: str = "abc123", repo: str = "alice/repo", msg: str = "feat: x") -> Commit:
    return Commit(
        sha=sha,
        repo=repo,
        message=msg,
        author_name="Alice",
        author_email="alice@example.com",
        timestamp=datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),
        url=f"https://github.com/{repo}/commit/{sha}",
    )


def _pr(pr_id: int = 1, repo: str = "alice/repo", state: str = "open") -> PullRequest:
    return PullRequest(
        pr_id=pr_id,
        repo=repo,
        title="Add feature",
        body="Body text.",
        state=state,
        merged_at=None,
        created_at=datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC),
        url=f"https://github.com/{repo}/pull/{pr_id}",
    )


def _issue(issue_id: int = 7, repo: str = "alice/repo", state: str = "open") -> Issue:
    return Issue(
        issue_id=issue_id,
        repo=repo,
        title="Bug report",
        body="Description.",
        state=state,
        created_at=datetime(2026, 5, 8, 9, 0, 0, tzinfo=UTC),
        closed_at=None,
        url=f"https://github.com/{repo}/issues/{issue_id}",
    )


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health(api_client: AsyncClient) -> None:
    resp = await api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /commits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commits_empty(api_client: AsyncClient) -> None:
    resp = await api_client.get("/commits")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_commits_returns_seeded_data(api_client: AsyncClient) -> None:
    await _seed(api_client, _commit("sha1"), _commit("sha2"))
    resp = await api_client.get("/commits")
    assert resp.status_code == 200
    shas = {c["sha"] for c in resp.json()}
    assert shas == {"sha1", "sha2"}


@pytest.mark.asyncio
async def test_commits_repo_filter(api_client: AsyncClient) -> None:
    await _seed(api_client, _commit("sha1", repo="alice/alpha"), _commit("sha2", repo="alice/beta"))
    resp = await api_client.get("/commits", params={"repo": "alice/alpha"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["sha"] == "sha1"


@pytest.mark.asyncio
async def test_commits_limit(api_client: AsyncClient) -> None:
    await _seed(api_client, *[_commit(f"sha{i}") for i in range(5)])
    resp = await api_client.get("/commits", params={"limit": 3})
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_commits_limit_zero_returns_422(api_client: AsyncClient) -> None:
    assert (await api_client.get("/commits", params={"limit": 0})).status_code == 422


@pytest.mark.asyncio
async def test_commits_limit_over_max_returns_422(api_client: AsyncClient) -> None:
    assert (await api_client.get("/commits", params={"limit": 201})).status_code == 422


# ---------------------------------------------------------------------------
# GET /pull_requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pull_requests_empty(api_client: AsyncClient) -> None:
    resp = await api_client.get("/pull_requests")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_pull_requests_returns_seeded_data(api_client: AsyncClient) -> None:
    await _seed(api_client, _pr(1), _pr(2))
    resp = await api_client.get("/pull_requests")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_pull_requests_state_filter(api_client: AsyncClient) -> None:
    await _seed(api_client, _pr(1, state="open"), _pr(2, state="closed"))
    resp = await api_client.get("/pull_requests", params={"state": "open"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["state"] == "open"


@pytest.mark.asyncio
async def test_pull_requests_invalid_state_returns_422(api_client: AsyncClient) -> None:
    assert (await api_client.get("/pull_requests", params={"state": "merged"})).status_code == 422


@pytest.mark.asyncio
async def test_pull_requests_repo_filter(api_client: AsyncClient) -> None:
    await _seed(api_client, _pr(1, repo="alice/alpha"), _pr(2, repo="alice/beta"))
    resp = await api_client.get("/pull_requests", params={"repo": "alice/beta"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["pr_id"] == 2


# ---------------------------------------------------------------------------
# GET /issues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_issues_empty(api_client: AsyncClient) -> None:
    resp = await api_client.get("/issues")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_issues_returns_seeded_data(api_client: AsyncClient) -> None:
    await _seed(api_client, _issue(1), _issue(2))
    resp = await api_client.get("/issues")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_issues_state_filter(api_client: AsyncClient) -> None:
    await _seed(api_client, _issue(1, state="open"), _issue(2, state="closed"))
    resp = await api_client.get("/issues", params={"state": "closed"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["state"] == "closed"


@pytest.mark.asyncio
async def test_issues_invalid_state_returns_422(api_client: AsyncClient) -> None:
    assert (await api_client.get("/issues", params={"state": "invalid"})).status_code == 422


@pytest.mark.asyncio
async def test_issues_repo_filter(api_client: AsyncClient) -> None:
    await _seed(api_client, _issue(1, repo="alice/alpha"), _issue(2, repo="alice/beta"))
    resp = await api_client.get("/issues", params={"repo": "alice/alpha"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["issue_id"] == 1


@pytest.mark.asyncio
async def test_issues_limit(api_client: AsyncClient) -> None:
    await _seed(api_client, *[_issue(i) for i in range(1, 6)])
    resp = await api_client.get("/issues", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2
