"""Ingestion worker — fetches GitHub activity and persists it to the database.

Run as: python -m pulse.ingestion.worker
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx

from pulse.config import settings
from pulse.db.engine import get_session, run_migrations
from pulse.db.repository import upsert_commit, upsert_issue, upsert_pull_request
from pulse.ingestion.github_client import GitHubClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 30

# HTTP status codes that indicate the token itself is broken, not a per-repo
# problem.  We abort immediately rather than hammering every subsequent repo
# with calls that will also fail.
_FATAL_STATUS_CODES = frozenset({401, 403, 429})


def _is_fatal(exc: httpx.HTTPStatusError) -> bool:
    """Return True when the error cannot be resolved by skipping to the next repo."""
    return exc.response.status_code in _FATAL_STATUS_CODES


async def ingest_repo(repo: str, since: datetime, client: GitHubClient) -> None:
    logger.info("Ingesting %s since %s", repo, since.date())

    # Fetch all data before opening a DB session so no connection is held
    # open during network I/O.
    commits = client.get_commits(repo, since)
    prs = client.get_pull_requests(repo, since)
    issues = client.get_issues(repo, since)
    logger.info("  %d commits, %d PRs, %d issues", len(commits), len(prs), len(issues))

    async with get_session() as session:
        for commit in commits:
            await upsert_commit(session, commit)
        for pr in prs:
            await upsert_pull_request(session, pr)
        for issue in issues:
            await upsert_issue(session, issue)


async def main() -> None:
    logger.info("Running migrations…")
    await run_migrations()

    since = datetime.now(tz=UTC) - timedelta(days=LOOKBACK_DAYS)

    with GitHubClient() as client:
        repos = settings.github_repo_list
        if not repos:
            logger.info("No GITHUB_REPOS set — fetching all repos for %s", settings.github_username)
            repos = client.list_repos(settings.github_username)

        logger.info("Ingesting %d repos", len(repos))
        for repo in repos:
            try:
                await ingest_repo(repo, since, client)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    logger.critical(
                        "GitHub token is invalid or lacks permissions (HTTP %d) — aborting",
                        status,
                    )
                    raise
                if status == 429:
                    logger.critical(
                        "Rate limit exhausted after all retries (HTTP 429) — aborting; "
                        "remaining repos will not be ingested",
                    )
                    raise
                logger.exception("Failed to ingest %s — skipping", repo)
            except Exception:
                logger.exception("Failed to ingest %s — skipping", repo)

    logger.info("Ingestion complete")


if __name__ == "__main__":
    asyncio.run(main())
