"""Ingestion worker — fetches GitHub activity and persists it to the database.

Run as: python -m pulse.ingestion.worker
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

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


async def ingest_repo(repo: str, since: datetime, client: GitHubClient) -> None:
    logger.info("Ingesting %s since %s", repo, since.date())

    commits = client.get_commits(repo, since)
    logger.info("  %d commits", len(commits))
    async with get_session() as session:
        for commit in commits:
            await upsert_commit(session, commit)

    prs = client.get_pull_requests(repo, since)
    logger.info("  %d pull requests", len(prs))
    async with get_session() as session:
        for pr in prs:
            await upsert_pull_request(session, pr)

    issues = client.get_issues(repo, since)
    logger.info("  %d issues", len(issues))
    async with get_session() as session:
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
            except Exception:
                logger.exception("Failed to ingest %s", repo)

    logger.info("Ingestion complete")


if __name__ == "__main__":
    asyncio.run(main())
