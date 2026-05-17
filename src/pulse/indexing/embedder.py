"""Embedder — generates vector embeddings for activity records.

TODO (Milestone 2):
- Use openai.embeddings or anthropic.embeddings to produce 1536-dim vectors
- Batch requests to respect rate limits
- Expose: embed_texts(texts: list[str]) -> list[list[float]]
"""

from __future__ import annotations


def embed_texts(texts: list[str]) -> list[list[float]]:  # noqa: ARG001
    raise NotImplementedError("Embedder not yet implemented (Milestone 2)")
