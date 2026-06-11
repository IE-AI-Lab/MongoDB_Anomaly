"""RAG primitives — knowledge search over `knowledge_base`.

Sync PyMongo variant (matches db.py / config.py in this service).

Embeddings are **managed by MongoDB Atlas Vector Search** via Automated Embedding
(Voyage AI). Atlas generates embeddings at index time for `text_content` and at
query time for the query text — this service never computes, normalizes, or stores
a vector. Chat/agent reasoning still uses Groq (see config.groq_* / chat_model).

Depends on:
- The `knowledge_vector` autoEmbed index on knowledge_base.text_content, using the
  model in config.voyage_embed_model() (created via the Atlas UI).
- knowledge_base seeded with `text_content` (scripts/init_db.py / knowledge_seed).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..core import config
from ..core.db import col

log = logging.getLogger(__name__)

KNOWLEDGE_INDEX = "knowledge_vector"
KNOWLEDGE_PATH = "text_content"


def search_knowledge(
    query: str,
    *,
    equipment_type: Optional[str] = None,
    error_codes: Optional[list[str]] = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Vector search with optional equipment_type + error_code filters.

    Uses Atlas Automated Embedding: the raw `query` text is embedded by Atlas with
    the same model the index uses, so we pass `query` (not a precomputed vector).

    Falls back to a plain filtered date sort if Atlas Vector Search is unavailable
    (e.g. the index is not Active yet). Only returns active entries — feedback
    awaiting curation has is_active=False (see feedback_to_knowledge.py).
    """
    knowledge_base = col("knowledge_base")

    pre_filter: dict[str, Any] = {"is_active": True}
    if equipment_type:
        pre_filter["equipment_type"] = equipment_type
    if error_codes:
        pre_filter["associated_error_codes"] = {"$in": error_codes}

    pipeline = [
        {
            "$vectorSearch": {
                "index": KNOWLEDGE_INDEX,
                "path": KNOWLEDGE_PATH,
                "query": query,
                "model": config.voyage_embed_model(),
                "numCandidates": max(50, k * 10),
                "limit": k,
                "filter": pre_filter,
            }
        },
        {"$project": {"_id": 0}},
    ]

    try:
        results = list(knowledge_base.aggregate(pipeline))
        if results:
            return results
        # Atlas returns an empty result set (no error) when the vector index does
        # not exist yet — so empty also means "fall back", not just exceptions.
        # With a live index, top-k similarity always returns docs.
        log.warning(
            "vector search returned 0 docs — index '%s' likely not Active yet; "
            "falling back to filtered date sort",
            KNOWLEDGE_INDEX,
        )
    except Exception as e:
        log.warning("vector search failed (%s) — falling back to filtered date sort", e)

    cursor = (
        knowledge_base.find(pre_filter, {"_id": 0})
        .sort("ingested_at_utc", -1)
        .limit(k)
    )
    return list(cursor)
