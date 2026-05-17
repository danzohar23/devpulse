"""Embedding generation using OpenAI text-embedding-3-small."""

from __future__ import annotations

from openai import OpenAI

from pulse.config import settings
from pulse.models import EMBEDDING_DIM

_MODEL = "text-embedding-3-small"
_BATCH_SIZE = 100


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per input text.

    Texts are sent to the OpenAI embeddings API in batches of up to
    _BATCH_SIZE to stay within request size limits. The returned list
    preserves the order of the input.
    """
    if not texts:
        return []

    client = OpenAI(api_key=settings.openai_api_key)
    results: list[list[float]] = []

    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        response = client.embeddings.create(
            model=_MODEL,
            input=batch,
            dimensions=EMBEDDING_DIM,
        )
        # API guarantees items are returned in index order, but sort defensively.
        ordered = sorted(response.data, key=lambda e: e.index)
        results.extend(e.embedding for e in ordered)

    return results
