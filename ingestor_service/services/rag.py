"""RAG primitives — hybrid knowledge search over `knowledge_base`.

Sync PyMongo variant (matches db.py / config.py in this service).

**Hybrid retrieval** = Atlas Vector Search (semantic) MERGED with a lexical
keyword match. Why both:
- Vector search (Atlas Automated Embedding / Voyage) finds conceptually similar
  docs but is weak on exact tokens (worker names, error codes, sensor IDs) and is
  blind to documents not yet embedded into the index (indexing lag / new inserts).
- The keyword pass catches those — so a freshly-added rule like "if temperature is
  high, call Daniel" is retrievable immediately, even before it is vector-indexed.

The two result lists are interleaved (keyword-first) and de-duplicated by
`document_id`. If both come back empty we fall back to a recency sort. Only active
entries are returned (feedback awaiting curation has is_active=False).

Embeddings are managed by Atlas (we never compute/store a vector). The vector
index `knowledge_vector` embeds `text_content` with config.voyage_embed_model().
"""

from __future__ import annotations

import logging
import re
from itertools import zip_longest
from typing import Any, Optional

from ..core import config
from ..core.db import col

log = logging.getLogger(__name__)

KNOWLEDGE_INDEX = "knowledge_vector"
KNOWLEDGE_PATH = "text_content"

# Dropped from keyword queries so common words don't match everything.
_STOPWORDS = frozenset(
    """a an and any are as at be been by do does for from has have how if in is it
    its no not of on or should that the then there this to was were what when which
    who why will with you your above below than over under into out""".split()
)


def _query_terms(query: str) -> list[str]:
    """Distinctive lowercase tokens from the query (deduped, no stopwords/short)."""
    words = re.findall(r"[a-z0-9_]+", query.lower())
    return [w for w in dict.fromkeys(words) if len(w) > 2 and w not in _STOPWORDS]


def _vector_search(query: str, pre_filter: dict[str, Any], k: int) -> list[dict[str, Any]]:
    """Atlas $vectorSearch (semantic). Returns [] if the index is unavailable."""
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
        return list(col("knowledge_base").aggregate(pipeline))
    except Exception as e:  # noqa: BLE001 — index missing / fake collection in tests
        log.warning("vector search failed (%s) — using keyword + recency only", e)
        return []


def _keyword_search(query: str, k: int) -> list[dict[str, Any]]:
    """Lexical recall: active docs whose text/title contain query terms, ranked by
    how many distinct terms they match. Filtered only by is_active so manually
    added rules (which often lack equipment_type/error_codes) still surface."""
    terms = _query_terms(query)
    if not terms:
        return []

    ors: list[dict[str, Any]] = []
    for t in terms:
        rx = {"$regex": re.escape(t), "$options": "i"}
        ors.append({"text_content": rx})
        ors.append({"section_title": rx})

    try:
        candidates = list(
            col("knowledge_base").find({"is_active": True, "$or": ors}, {"_id": 0})
        )
    except Exception as e:  # noqa: BLE001
        log.warning("keyword search failed (%s)", e)
        return []

    def score(doc: dict[str, Any]) -> int:
        blob = f"{doc.get('section_title', '')} {doc.get('text_content', '')}".lower()
        return sum(1 for t in terms if t in blob)

    candidates.sort(key=score, reverse=True)
    return candidates[:k]


def _merge(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Interleave two ranked lists (primary first), de-duped by document_id, top k."""
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for pair in zip_longest(primary, secondary):
        for doc in pair:
            if doc is None:
                continue
            key = doc.get("document_id") or id(doc)
            if key in seen:
                continue
            seen.add(key)
            out.append(doc)
            if len(out) >= k:
                return out
    return out[:k]


def search_knowledge(
    query: str,
    *,
    equipment_type: Optional[str] = None,
    error_codes: Optional[list[str]] = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Hybrid knowledge search: semantic vector results merged with keyword hits.

    Uses Atlas Automated Embedding for the vector half (the raw `query` text is
    embedded by Atlas), and a lexical keyword pass for recall on exact terms and
    not-yet-indexed documents. Falls back to a filtered recency sort if both are
    empty (e.g. the vector index is not Active and no keyword overlap).
    """
    pre_filter: dict[str, Any] = {"is_active": True}
    if equipment_type:
        pre_filter["equipment_type"] = equipment_type
    if error_codes:
        pre_filter["associated_error_codes"] = {"$in": error_codes}

    vector_results = _vector_search(query, pre_filter, k)
    keyword_results = _keyword_search(query, k)

    merged = _merge(keyword_results, vector_results, k)
    if merged:
        return merged

    log.warning(
        "vector + keyword search returned 0 docs — falling back to filtered date sort"
    )
    cursor = (
        col("knowledge_base")
        .find(pre_filter, {"_id": 0})
        .sort("ingested_at_utc", -1)
        .limit(k)
    )
    return list(cursor)
