from __future__ import annotations

# Set required env vars before any pulse module is imported so that
# pydantic-settings doesn't error during collection.
import os

os.environ.setdefault("GITHUB_TOKEN", "ghp_test_token")
os.environ.setdefault("GITHUB_USERNAME", "testuser")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pulse.models import Base


@pytest.fixture
def github_token() -> str:
    return "ghp_fake_token_for_testing"


@pytest.fixture
def mock_github_responses() -> dict:
    """Sample JSON matching the GitHub API shape for commits, PRs, and issues."""
    return {
        "commits": [
            {
                "sha": "abc123def456",
                "commit": {
                    "message": "feat: add new feature",
                    "author": {
                        "name": "Alice Dev",
                        "email": "alice@example.com",
                        "date": "2026-05-10T12:00:00Z",
                    },
                },
                "html_url": "https://github.com/alice/repo/commit/abc123def456",
            }
        ],
        "pull_requests": [
            {
                "number": 42,
                "title": "Add new feature",
                "body": "This PR adds a new feature.",
                "state": "open",
                "merged_at": None,
                "created_at": "2026-05-09T10:00:00Z",
                "html_url": "https://github.com/alice/repo/pull/42",
            }
        ],
        "issues": [
            {
                "number": 7,
                "title": "Bug: something is broken",
                "body": "Detailed description of the bug.",
                "state": "open",
                "created_at": "2026-05-08T09:00:00Z",
                "closed_at": None,
                "html_url": "https://github.com/alice/repo/issues/7",
                # no 'pull_request' key — this is a real issue
            }
        ],
    }


# ---------------------------------------------------------------------------
# Async SQLite in-memory database for repository tests
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def _session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async with _session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
