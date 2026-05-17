"""REST endpoints for querying stored GitHub activity."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pulse.api.dependencies import get_db_session
from pulse.db import repository
from pulse.models import Commit, Issue, PullRequest

router = APIRouter()

_MAX_LIMIT = 200


@router.get("/commits", response_model=list[Commit], summary="List recent commits")
async def list_commits(
    repo: Annotated[
        str | None,
        Query(description="Filter by repository slug, e.g. owner/repo"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=_MAX_LIMIT, description="Max results (1-200)"),
    ] = 50,
    session: AsyncSession = Depends(get_db_session),
) -> list[Commit]:
    return await repository.get_recent_commits(session, repo=repo, limit=limit)


@router.get("/pull_requests", response_model=list[PullRequest], summary="List recent pull requests")
async def list_pull_requests(
    repo: Annotated[
        str | None,
        Query(description="Filter by repository slug, e.g. owner/repo"),
    ] = None,
    state: Annotated[
        Literal["open", "closed"] | None,
        Query(description="Filter by PR state: open or closed"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=_MAX_LIMIT, description="Max results (1-200)"),
    ] = 50,
    session: AsyncSession = Depends(get_db_session),
) -> list[PullRequest]:
    return await repository.get_recent_pull_requests(
        session, repo=repo, state=state, limit=limit
    )


@router.get("/issues", response_model=list[Issue], summary="List recent issues")
async def list_issues(
    repo: Annotated[
        str | None,
        Query(description="Filter by repository slug, e.g. owner/repo"),
    ] = None,
    state: Annotated[
        Literal["open", "closed"] | None,
        Query(description="Filter by issue state: open or closed"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=_MAX_LIMIT, description="Max results (1-200)"),
    ] = 50,
    session: AsyncSession = Depends(get_db_session),
) -> list[Issue]:
    return await repository.get_recent_issues(
        session, repo=repo, state=state, limit=limit
    )
