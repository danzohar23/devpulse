"""Indexer — drives the embedding pipeline over stored activity records.

TODO (Milestone 2):
- Query repository for records with NULL embedding column
- Call embedder.embed_texts() in batches
- Write embeddings back via repository update functions
- Build pgvector HNSW index after initial bulk load
"""

from __future__ import annotations


async def run_indexing() -> None:
    raise NotImplementedError("Indexer not yet implemented (Milestone 2)")
