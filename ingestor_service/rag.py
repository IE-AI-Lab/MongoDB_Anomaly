"""RAG primitives — embedding + knowledge search over `knowledge_base`.

Sync PyMongo variant (matches db.py / config.py in this service).

Embeddings use Google Gemini (Groq has no embeddings endpoint). Chat/agent
reasoning uses Groq — see config.groq_* / config.chat_model.

Depends on:
- config.google_api_key() / config.embed_model() (step 04)
- `knowledge_vector` Atlas Search index on knowledge_base.text_embedding (step 03)
- knowledge_base collection seeded with embeddings (step 02)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from google import genai
from google.genai import types

from . import config
from .db import col

log = logging.getLogger(__name__)

_client: Optional[genai.Client] = None


def _gemini() -> genai.Client:
    global _client
    if _client is None:
        api_key = config.google_api_key()
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set — required for embeddings. "
                "See .env.example."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def embed(text: str) -> list[float]:
    """Embed a single string.

    Uses gemini-embedding-001, truncated to config.embed_dimensions() (768 by
    default) via Matryoshka representation. Truncated vectors are not
    unit-norm, so we L2-normalize for correct cosine similarity in Atlas.
    """
    dims = config.embed_dimensions()
    resp = _gemini().models.embed_content(
        model=config.embed_model(),
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=dims),
    )
    values = list(resp.embeddings[0].values)

    norm = math.sqrt(sum(x * x for x in values))
    if norm:
        values = [x / norm for x in values]
    return values


def search_knowledge(
    query: str,
    *,
    equipment_type: Optional[str] = None,
    error_codes: Optional[list[str]] = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Vector search with optional equipment_type + error_code filters.

    Falls back to a plain filtered date sort if Atlas Vector Search is
    unavailable (e.g. local Mongo without the index). Only returns active
    entries — feedback awaiting curation has is_active=False (see step 07).
    """
    knowledge_base = col("knowledge_base")
    vec = embed(query)

    pre_filter: dict[str, Any] = {"is_active": True}
    if equipment_type:
        pre_filter["equipment_type"] = equipment_type
    if error_codes:
        pre_filter["associated_error_codes"] = {"$in": error_codes}

    pipeline = [
        {
            "$vectorSearch": {
                "index": "knowledge_vector",
                "path": "text_embedding",
                "queryVector": vec,
                "numCandidates": max(50, k * 10),
                "limit": k,
                "filter": pre_filter,
            }
        },
        {"$project": {"text_embedding": 0}},
    ]

    try:
        return list(knowledge_base.aggregate(pipeline))
    except Exception as e:
        log.warning("vector search failed (%s) — falling back to filtered date sort", e)
        cursor = (
            knowledge_base.find(pre_filter, {"text_embedding": 0})
            .sort("ingested_at_utc", -1)
            .limit(k)
        )
        return list(cursor)
