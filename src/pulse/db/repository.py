"""Database access layer — all DB queries live here."""
from __future__ import annotations

from typing import Any

import asyncpg
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

    Uses cosine distance via pgvector's <=> operator. Each entity type
    contributes up to `limit` candidates; the final list is re-ranked
    globally and trimmed to `limit`.

    Raises:
        NotImplementedError: when the underlying database is not PostgreSQL
            (pgvector operators are unavailable on other backends).
    """
    conn = await session.connection()
    if conn.dialect.name != "postgresql":
        raise NotImplementedError(
            "search_similar requires PostgreSQL with pgvector — SQLite is not supported"
        )

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


# ---------------------------------------------------------------------------
# Direct-asyncpg queries — MCP server production path
#
# SQLAlchemy's greenlet bridge (greenlet_spawn) deadlocks inside anyio's
# cancel-scope stack on Windows, so the MCP server's call_tool handler cannot
# use get_session()-based queries.  These functions use asyncpg directly and
# avoid the greenlet bridge entirely.  The SQLAlchemy functions above remain
# the path for the test suite (SQLite in-memory) and all non-MCP callers.
# ---------------------------------------------------------------------------


def _dt(v: object) -> str | None:
    """Serialise a datetime (or None) to an ISO-8601 string."""
    return v.isoformat() if v is not None else None  # type: ignore[union-attr]


async def get_commits_asyncpg(
    pool: asyncpg.Pool,
    repo: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return recent commits via a direct asyncpg query."""
    async with pool.acquire() as conn:
        if repo is not None:
            rows = await conn.fetch(
                "SELECT sha, repo, message, author_name, author_email, timestamp, url"
                " FROM commits WHERE repo = $1 ORDER BY timestamp DESC LIMIT $2",
                repo,
                limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT sha, repo, message, author_name, author_email, timestamp, url"
                " FROM commits ORDER BY timestamp DESC LIMIT $1",
                limit,
            )
    return [
        {
            "sha": r["sha"],
            "repo": r["repo"],
            "message": r["message"],
            "author_name": r["author_name"],
            "author_email": r["author_email"],
            "timestamp": _dt(r["timestamp"]),
            "url": r["url"],
        }
        for r in rows
    ]


async def get_pull_requests_asyncpg(
    pool: asyncpg.Pool,
    repo: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return recent pull requests via a direct asyncpg query."""
    conditions: list[str] = []
    params: list = []
    if repo is not None:
        params.append(repo)
        conditions.append(f"repo = ${len(params)}")
    if state is not None:
        params.append(state)
        conditions.append(f"state = ${len(params)}")
    params.append(limit)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT pr_id, repo, title, body, state, merged_at, created_at, url"
            f" FROM pull_requests {where} ORDER BY created_at DESC LIMIT ${len(params)}",
            *params,
        )
    return [
        {
            "pr_id": r["pr_id"],
            "repo": r["repo"],
            "title": r["title"],
            "body": r["body"],
            "state": r["state"],
            "merged_at": _dt(r["merged_at"]),
            "created_at": _dt(r["created_at"]),
            "url": r["url"],
        }
        for r in rows
    ]


async def get_issues_asyncpg(
    pool: asyncpg.Pool,
    repo: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return recent issues via a direct asyncpg query."""
    conditions: list[str] = []
    params: list = []
    if repo is not None:
        params.append(repo)
        conditions.append(f"repo = ${len(params)}")
    if state is not None:
        params.append(state)
        conditions.append(f"state = ${len(params)}")
    params.append(limit)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT issue_id, repo, title, body, state, created_at, closed_at, url"
            f" FROM issues {where} ORDER BY created_at DESC LIMIT ${len(params)}",
            *params,
        )
    return [
        {
            "issue_id": r["issue_id"],
            "repo": r["repo"],
            "title": r["title"],
            "body": r["body"],
            "state": r["state"],
            "created_at": _dt(r["created_at"]),
            "closed_at": _dt(r["closed_at"]),
            "url": r["url"],
        }
        for r in rows
    ]


async def search_activity_asyncpg(
    pool: asyncpg.Pool,
    embedding: list[float],
    repo: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Semantic similarity search via direct asyncpg (mirrors search_similar).

    Raises NotImplementedError when pgvector is not installed on the server.
    """
    vec = "[" + ",".join(str(x) for x in embedding) + "]"
    repo_filter = "AND repo = $3" if repo is not None else ""

    results: list[dict] = []
    async with pool.acquire() as conn:
        for row_type, tbl, title_col, body_expr, state_expr, ts_col in [
            ("commit",       "commits",       "message", "NULL::text", "NULL::text", "timestamp"),
            ("pull_request", "pull_requests", "title",   "body",       "state",      "created_at"),
            ("issue",        "issues",        "title",   "body",       "state",      "created_at"),
        ]:
            params: list = [vec, limit]
            if repo is not None:
                params.append(repo)
            try:
                rows = await conn.fetch(
                    f"""
                    SELECT '{row_type}'::text AS type,
                           1 - (embedding <=> CAST($1 AS vector)) AS score,
                           repo, url,
                           {title_col} AS title,
                           {body_expr} AS body,
                           {state_expr} AS state,
                           {ts_col} AS created_at
                    FROM   {tbl}
                    WHERE  embedding IS NOT NULL {repo_filter}
                    ORDER BY embedding <=> CAST($1 AS vector)
                    LIMIT $2
                    """,
                    *params,
                )
            except asyncpg.UndefinedObjectError:
                raise NotImplementedError(
                    "search_activity requires PostgreSQL with pgvector"
                )
            for r in rows:
                results.append(
                    {
                        "type": r["type"],
                        "score": float(r["score"]),
                        "repo": r["repo"],
                        "url": r["url"],
                        "title": r["title"],
                        "body": r["body"],
                        "state": r["state"],
                        "created_at": _dt(r["created_at"]),
                    }
                )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
