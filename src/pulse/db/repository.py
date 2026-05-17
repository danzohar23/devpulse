"""Database access layer — all DB queries live here."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from pulse.models import (
    Commit,
    CommitRecord,
    Issue,
    IssueRecord,
    PullRequest,
    PullRequestRecord,
    SearchResult,
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


async def _insert_update(
    session: AsyncSession,
    model: Any,
    values: dict[str, Any],
    conflict_cols: list[str],
    update_cols: list[str],
) -> None:
    """Dialect-aware INSERT ... ON CONFLICT DO UPDATE on the specified columns."""
    conn = await session.connection()
    dialect_name = conn.dialect.name
    update_set = {col: values[col] for col in update_cols}
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = (
            sqlite_insert(model)
            .values(**values)
            .on_conflict_do_update(index_elements=conflict_cols, set_=update_set)
        )
    else:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(model)
            .values(**values)
            .on_conflict_do_update(index_elements=conflict_cols, set_=update_set)
        )
    await session.execute(stmt)


# ---------------------------------------------------------------------------
# Ingestion upserts
# ---------------------------------------------------------------------------


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
    await _insert_update(
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
        ["state", "merged_at"],
    )


async def upsert_issue(session: AsyncSession, issue: Issue) -> None:
    await _insert_update(
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
        ["state", "closed_at"],
    )


# ---------------------------------------------------------------------------
# Recent-record queries
# ---------------------------------------------------------------------------


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
    state: str | None = None,
    limit: int = 50,
) -> list[PullRequest]:
    q = select(PullRequestRecord).order_by(PullRequestRecord.created_at.desc()).limit(limit)
    if repo is not None:
        q = q.where(PullRequestRecord.repo == repo)
    if state is not None:
        q = q.where(PullRequestRecord.state == state)
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
    state: str | None = None,
    limit: int = 50,
) -> list[Issue]:
    q = select(IssueRecord).order_by(IssueRecord.created_at.desc()).limit(limit)
    if repo is not None:
        q = q.where(IssueRecord.repo == repo)
    if state is not None:
        q = q.where(IssueRecord.state == state)
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


# ---------------------------------------------------------------------------
# Embedding writes — called by the indexer after generating vectors
# ---------------------------------------------------------------------------


async def set_commit_embedding(
    session: AsyncSession,
    sha: str,
    embedding: list[float],
) -> None:
    await session.execute(
        update(CommitRecord).where(CommitRecord.sha == sha).values(embedding=embedding)
    )


async def set_pull_request_embedding(
    session: AsyncSession,
    pr_id: int,
    repo: str,
    embedding: list[float],
) -> None:
    await session.execute(
        update(PullRequestRecord)
        .where(PullRequestRecord.pr_id == pr_id, PullRequestRecord.repo == repo)
        .values(embedding=embedding)
    )


async def set_issue_embedding(
    session: AsyncSession,
    issue_id: int,
    repo: str,
    embedding: list[float],
) -> None:
    await session.execute(
        update(IssueRecord)
        .where(IssueRecord.issue_id == issue_id, IssueRecord.repo == repo)
        .values(embedding=embedding)
    )


# ---------------------------------------------------------------------------
# Unindexed-record queries — used by the incremental indexer
# ---------------------------------------------------------------------------


async def get_unindexed_commits(
    session: AsyncSession,
    batch_size: int = 100,
) -> list[Commit]:
    q = (
        select(CommitRecord)
        .where(CommitRecord.embedding.is_(None))
        .limit(batch_size)
    )
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


async def get_unindexed_pull_requests(
    session: AsyncSession,
    batch_size: int = 100,
) -> list[PullRequest]:
    q = (
        select(PullRequestRecord)
        .where(PullRequestRecord.embedding.is_(None))
        .limit(batch_size)
    )
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


async def get_unindexed_issues(
    session: AsyncSession,
    batch_size: int = 100,
) -> list[Issue]:
    q = (
        select(IssueRecord)
        .where(IssueRecord.embedding.is_(None))
        .limit(batch_size)
    )
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


# ---------------------------------------------------------------------------
# Vector similarity search — PostgreSQL + pgvector only
# ---------------------------------------------------------------------------

def _vec_param(embedding: list[float]) -> str:
    """Serialise a float list to the pgvector text literal format."""
    return "[" + ",".join(str(x) for x in embedding) + "]"


async def search_similar(
    session: AsyncSession,
    query_embedding: list[float],
    limit: int = 10,
    repo: str | None = None,
) -> list[SearchResult]:
    """Return the top-`limit` most semantically similar activity records.

    Uses cosine distance via pgvector's <=> operator. Returns an empty list
    when the underlying database is not PostgreSQL (e.g. during SQLite tests).
    Each entity type contributes up to `limit` candidates; the final list is
    re-ranked globally and trimmed to `limit`.
    """
    conn = await session.connection()
    if conn.dialect.name != "postgresql":
        return []

    vec = _vec_param(query_embedding)
    repo_filter = "AND repo = :repo" if repo is not None else ""
    params: dict[str, Any] = {"vec": vec, "n": limit}
    if repo is not None:
        params["repo"] = repo

    commit_sql = text(f"""
        SELECT 'commit'        AS type,
               1 - (embedding <=> CAST(:vec AS vector)) AS score,
               repo,
               url,
               message         AS title,
               NULL            AS body,
               NULL            AS state,
               timestamp       AS created_at
        FROM   commits
        WHERE  embedding IS NOT NULL {repo_filter}
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT  :n
    """)

    pr_sql = text(f"""
        SELECT 'pull_request'  AS type,
               1 - (embedding <=> CAST(:vec AS vector)) AS score,
               repo,
               url,
               title,
               body,
               state,
               created_at
        FROM   pull_requests
        WHERE  embedding IS NOT NULL {repo_filter}
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT  :n
    """)

    issue_sql = text(f"""
        SELECT 'issue'         AS type,
               1 - (embedding <=> CAST(:vec AS vector)) AS score,
               repo,
               url,
               title,
               body,
               state,
               created_at
        FROM   issues
        WHERE  embedding IS NOT NULL {repo_filter}
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT  :n
    """)

    results: list[SearchResult] = []
    for sql in (commit_sql, pr_sql, issue_sql):
        rows = (await session.execute(sql, params)).mappings().all()
        for r in rows:
            results.append(
                SearchResult(
                    type=r["type"],
                    score=float(r["score"]),
                    repo=r["repo"],
                    url=r["url"],
                    title=r["title"],
                    body=r["body"],
                    state=r["state"],
                    created_at=r["created_at"],
                )
            )

    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]
