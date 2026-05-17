"""Incremental indexer — embeds activity records that have no vector yet.

Run as: python -m pulse.indexing.indexer

The indexer is intentionally synchronous in its embedding calls: it fetches
a batch of unindexed records (async), generates embeddings via the OpenAI API
(sync, outside the session so no DB connection is held during network I/O),
writes the embeddings back (async), then repeats. This mirrors the worker
pattern described in ADR-010.
"""

from __future__ import annotations

import asyncio
import logging

from pulse.db.engine import get_session
from pulse.db.repository import (
    get_unindexed_commits,
    get_unindexed_issues,
    get_unindexed_pull_requests,
    set_commit_embedding,
    set_issue_embedding,
    set_pull_request_embedding,
)
from pulse.indexing.embedder import embed_texts
from pulse.models import Commit, Issue, PullRequest

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


def _commit_text(c: Commit) -> str:
    return c.message


def _pr_text(pr: PullRequest) -> str:
    return f"{pr.title}\n\n{pr.body}".strip()


def _issue_text(issue: Issue) -> str:
    return f"{issue.title}\n\n{issue.body}".strip()


async def _index_commits(batch_size: int) -> int:
    """Embed one batch of unindexed commits. Returns the number processed."""
    async with get_session() as session:
        records = await get_unindexed_commits(session, batch_size)

    if not records:
        return 0

    texts = [_commit_text(r) for r in records]
    embeddings = embed_texts(texts)  # sync — runs outside the event loop's active I/O

    async with get_session() as session:
        for record, embedding in zip(records, embeddings, strict=True):
            await set_commit_embedding(session, record.sha, embedding)

    return len(records)


async def _index_pull_requests(batch_size: int) -> int:
    async with get_session() as session:
        records = await get_unindexed_pull_requests(session, batch_size)

    if not records:
        return 0

    texts = [_pr_text(r) for r in records]
    embeddings = embed_texts(texts)

    async with get_session() as session:
        for record, embedding in zip(records, embeddings, strict=True):
            await set_pull_request_embedding(session, record.pr_id, record.repo, embedding)

    return len(records)


async def _index_issues(batch_size: int) -> int:
    async with get_session() as session:
        records = await get_unindexed_issues(session, batch_size)

    if not records:
        return 0

    texts = [_issue_text(r) for r in records]
    embeddings = embed_texts(texts)

    async with get_session() as session:
        for record, embedding in zip(records, embeddings, strict=True):
            await set_issue_embedding(session, record.issue_id, record.repo, embedding)

    return len(records)


async def run_indexing(batch_size: int = _BATCH_SIZE) -> None:
    """Incrementally embed all records that currently have no embedding.

    Loops over each entity type until all pending records are processed.
    """
    total = 0

    for label, index_fn in (
        ("commits", _index_commits),
        ("pull_requests", _index_pull_requests),
        ("issues", _index_issues),
    ):
        processed = await index_fn(batch_size)
        while processed:
            total += processed
            logger.info("Indexed %d %s (running total: %d)", processed, label, total)
            processed = await index_fn(batch_size)

    logger.info("Indexing complete — %d records embedded", total)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    asyncio.run(run_indexing())
