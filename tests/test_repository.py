from __future__ import annotations

from datetime import datetime, timezone
UTC = timezone.utc

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pulse.db.repository import (
    get_recent_commits,
    upsert_commit,
    upsert_issue,
    upsert_pull_request,
)
from pulse.models import Commit, Issue, PullRequest

_TS = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


def _commit(sha: str = "abc123", repo: str = "owner/repo") -> Commit:
    return Commit(
        sha=sha,
        repo=repo,
        message="test commit",
        author_name="Dev",
        author_email="dev@example.com",
        timestamp=_TS,
        url=f"https://github.com/{repo}/commit/{sha}",
    )


def _pr(pr_id: int = 1, repo: str = "owner/repo") -> PullRequest:
    return PullRequest(
        pr_id=pr_id,
        repo=repo,
        title="Test PR",
        body="Test body",
        state="open",
        merged_at=None,
        created_at=_TS,
        url=f"https://github.com/{repo}/pull/{pr_id}",
    )


def _issue(issue_id: int = 1, repo: str = "owner/repo") -> Issue:
    return Issue(
        issue_id=issue_id,
        repo=repo,
        title="Test issue",
        body="Test body",
        state="open",
        created_at=_TS,
        closed_at=None,
        url=f"https://github.com/{repo}/issues/{issue_id}",
    )


@pytest.mark.asyncio
async def test_upsert_commit_idempotent(db_session: AsyncSession) -> None:
    commit = _commit()
    await upsert_commit(db_session, commit)
    await upsert_commit(db_session, commit)
    await db_session.commit()

    results = await get_recent_commits(db_session)
    assert len(results) == 1
    assert results[0].sha == commit.sha


@pytest.mark.asyncio
async def test_upsert_pr_idempotent(db_session: AsyncSession) -> None:
    pr = _pr()
    await upsert_pull_request(db_session, pr)
    await upsert_pull_request(db_session, pr)
    await db_session.commit()

    from sqlalchemy import select

    from pulse.models import PullRequestRecord

    rows = list(await db_session.scalars(select(PullRequestRecord)))
    assert len(rows) == 1
    assert rows[0].pr_id == pr.pr_id


@pytest.mark.asyncio
async def test_upsert_issue_idempotent(db_session: AsyncSession) -> None:
    issue = _issue()
    await upsert_issue(db_session, issue)
    await upsert_issue(db_session, issue)
    await db_session.commit()

    from sqlalchemy import select

    from pulse.models import IssueRecord

    rows = list(await db_session.scalars(select(IssueRecord)))
    assert len(rows) == 1
    assert rows[0].issue_id == issue.issue_id


@pytest.mark.asyncio
async def test_get_recent_commits(db_session: AsyncSession) -> None:
    commits = [
        _commit(sha="sha1"),
        _commit(sha="sha2"),
        _commit(sha="sha3"),
    ]
    for c in commits:
        await upsert_commit(db_session, c)
    await db_session.commit()

    results = await get_recent_commits(db_session)
    assert len(results) == 3
    result_shas = {r.sha for r in results}
    assert result_shas == {"sha1", "sha2", "sha3"}
