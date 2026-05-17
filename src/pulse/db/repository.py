from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pulse.models import (
    Commit,
    CommitRecord,
    Issue,
    IssueRecord,
    PullRequest,
    PullRequestRecord,
)


async def _insert_ignore(
    session: AsyncSession,
    model: Any,
    values: dict[str, Any],
    conflict_cols: list[str],
) -> None:
    """Dialect-aware INSERT ... ON CONFLICT DO NOTHING."""
    conn = await session.connection()
    dialect_name = conn.dialect.name
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(model).values(**values).on_conflict_do_nothing()
    else:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(model).values(**values).on_conflict_do_nothing(
            index_elements=conflict_cols
        )
    await session.execute(stmt)


async def upsert_commit(session: AsyncSession, commit: Commit) -> None:
    await _insert_ignore(
        session,
        CommitRecord,
        {
            "sha": commit.sha,
            "repo": commit.repo,
            "message": commit.message,
            "author_name": commit.author_name,
            "author_email": commit.author_email,
            "timestamp": commit.timestamp,
            "url": commit.url,
        },
        ["sha"],
    )


async def upsert_pull_request(session: AsyncSession, pr: PullRequest) -> None:
    await _insert_ignore(
        session,
        PullRequestRecord,
        {
            "pr_id": pr.pr_id,
            "repo": pr.repo,
            "title": pr.title,
            "body": pr.body,
            "state": pr.state,
            "merged_at": pr.merged_at,
            "created_at": pr.created_at,
            "url": pr.url,
        },
        ["pr_id", "repo"],
    )


async def upsert_issue(session: AsyncSession, issue: Issue) -> None:
    await _insert_ignore(
        session,
        IssueRecord,
        {
            "issue_id": issue.issue_id,
            "repo": issue.repo,
            "title": issue.title,
            "body": issue.body,
            "state": issue.state,
            "created_at": issue.created_at,
            "closed_at": issue.closed_at,
            "url": issue.url,
        },
        ["issue_id", "repo"],
    )


async def get_recent_commits(
    session: AsyncSession,
    repo: str | None = None,
    limit: int = 50,
) -> list[Commit]:
    q = select(CommitRecord).order_by(CommitRecord.timestamp.desc()).limit(limit)
    if repo is not None:
        q = q.where(CommitRecord.repo == repo)
    rows = await session.scalars(q)
    return [
        Commit(
            sha=r.sha,
            repo=r.repo,
            message=r.message,
            author_name=r.author_name,
            author_email=r.author_email,
            timestamp=r.timestamp,
            url=r.url,
        )
        for r in rows
    ]


async def get_recent_pull_requests(
    session: AsyncSession,
    repo: str | None = None,
    limit: int = 50,
) -> list[PullRequest]:
    q = select(PullRequestRecord).order_by(PullRequestRecord.created_at.desc()).limit(limit)
    if repo is not None:
        q = q.where(PullRequestRecord.repo == repo)
    rows = await session.scalars(q)
    return [
        PullRequest(
            pr_id=r.pr_id,
            repo=r.repo,
            title=r.title,
            body=r.body,
            state=r.state,
            merged_at=r.merged_at,
            created_at=r.created_at,
            url=r.url,
        )
        for r in rows
    ]


async def get_recent_issues(
    session: AsyncSession,
    repo: str | None = None,
    limit: int = 50,
) -> list[Issue]:
    q = select(IssueRecord).order_by(IssueRecord.created_at.desc()).limit(limit)
    if repo is not None:
        q = q.where(IssueRecord.repo == repo)
    rows = await session.scalars(q)
    return [
        Issue(
            issue_id=r.issue_id,
            repo=r.repo,
            title=r.title,
            body=r.body,
            state=r.state,
            created_at=r.created_at,
            closed_at=r.closed_at,
            url=r.url,
        )
        for r in rows
    ]
