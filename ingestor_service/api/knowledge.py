"""Knowledge curation endpoints — CRUD over `knowledge_base`.

Sync PyMongo variant. Endpoints are plain `def` (FastAPI threadpools blocking
IO). Mounted via api/__init__.py's `all_routers`.

Why these exist: feedback entries land in `knowledge_base` with is_active=False
(see feedback_to_knowledge.py) awaiting human curation. Until now there was no
API to act on that queue — these endpoints make the guardrail real:

    GET    /knowledge?is_active=false&source=feedback   the review queue
    PATCH  /knowledge/{document_id}  {"is_active": true}  approve
    DELETE /knowledge/{document_id}                       reject

Embeddings are managed by Atlas autoEmbed — we only ever store `text_content`;
the `knowledge_vector` index picks up inserts/updates automatically.

ROUTE-ORDERING NOTE: `GET /knowledge/search` lives in api/read.py, whose router
sits BEFORE this one in api/__init__.py's `all_routers` — that ordering keeps the
literal `/knowledge/search` from being captured by `/knowledge/{document_id}`
here. Do not reorder `all_routers`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..core.db import col

router = APIRouter(tags=["knowledge"])

# Documents are sourced three ways, each with its own document_id prefix:
#   seed-NNN   scripts/init_db.py seed corpus
#   fb-UUID    field-resolution feedback (feedback_to_knowledge.py), is_active=False
#   kb-UUID    manual entries created via POST /knowledge
_SOURCE_PREFIX: dict[str, str] = {"seed": "seed-", "feedback": "fb-", "manual": "kb-"}


def _strip_mongo_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("_id", None)
    return doc


class KnowledgeCreate(BaseModel):
    section_title: str
    text_content: str  # Atlas autoEmbed generates the vector from this
    equipment_type: Optional[str] = None
    associated_error_codes: list[str] = []
    source_file: Optional[str] = None  # defaults to "manual" server-side
    page_number: Optional[int] = None
    is_active: bool = True


class KnowledgePatch(BaseModel):
    section_title: Optional[str] = None
    text_content: Optional[str] = None
    equipment_type: Optional[str] = None
    associated_error_codes: Optional[list[str]] = None
    is_active: Optional[bool] = None  # curator approval flips this to True


@router.get("/knowledge")
def list_knowledge(
    is_active: Optional[bool] = Query(None),
    equipment_type: Optional[str] = None,
    source: Optional[str] = Query(None, description="seed / feedback / manual"),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List knowledge entries. `?is_active=false&source=feedback` = review queue."""
    q: dict[str, Any] = {}
    if is_active is not None:
        q["is_active"] = is_active
    if equipment_type:
        q["equipment_type"] = equipment_type
    if source:
        prefix = _SOURCE_PREFIX.get(source)
        if prefix is None:
            raise HTTPException(
                400, f"invalid source '{source}'; must be one of {sorted(_SOURCE_PREFIX)}"
            )
        q["document_id"] = {"$regex": f"^{prefix}"}

    cursor = (
        col("knowledge_base")
        .find(q)
        .sort("ingested_at_utc", -1)
        .skip(skip)
        .limit(limit)
    )
    return [_strip_mongo_id(d) for d in cursor]


@router.get("/knowledge/{document_id}")
def get_knowledge(document_id: str) -> dict[str, Any]:
    # NB: never matches "search" — api/read.py's /knowledge/search registers first.
    doc = col("knowledge_base").find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(404, "knowledge entry not found")
    return _strip_mongo_id(doc)


@router.post("/knowledge", status_code=201)
def create_knowledge(entry: KnowledgeCreate) -> dict[str, Any]:
    """Create a knowledge entry. Atlas autoEmbed indexes text_content — no vector here."""
    now = datetime.now(timezone.utc)
    doc: dict[str, Any] = {
        "document_id": f"kb-{uuid.uuid4()}",
        "source_file": entry.source_file or "manual",
        "page_number": entry.page_number,
        "section_title": entry.section_title,
        "equipment_type": entry.equipment_type,
        "associated_error_codes": entry.associated_error_codes,
        "text_content": entry.text_content,
        "chunk_index": 0,
        "is_active": entry.is_active,
        "ingested_at_utc": now,
        "schema_version": 1,
    }
    col("knowledge_base").insert_one(doc)
    return _strip_mongo_id(doc)


@router.patch("/knowledge/{document_id}")
def patch_knowledge(document_id: str, patch: KnowledgePatch) -> dict[str, Any]:
    """Partial update. Curator approval = {"is_active": true} on a feedback entry."""
    update = {
        k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None
    }
    if not update:
        raise HTTPException(400, "no fields to update")

    existing = col("knowledge_base").find_one({"document_id": document_id})
    if not existing:
        raise HTTPException(404, "knowledge entry not found")

    update["updated_at_utc"] = datetime.now(timezone.utc)
    col("knowledge_base").update_one({"document_id": document_id}, {"$set": update})
    return _strip_mongo_id(col("knowledge_base").find_one({"document_id": document_id}))


@router.delete("/knowledge/{document_id}")
def delete_knowledge(document_id: str) -> dict[str, Any]:
    """Hard delete. Curator rejection of a feedback entry."""
    result = col("knowledge_base").delete_one({"document_id": document_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "knowledge entry not found")
    return {"deleted": True, "document_id": document_id}
