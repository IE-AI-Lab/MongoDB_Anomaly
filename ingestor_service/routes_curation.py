"""Curation endpoints — human review of the closed RAG feedback loop.

When an anomaly is resolved with outcome="fixed", feedback_to_knowledge.py
inserts the resolution notes into knowledge_base with is_active=False and
curation_status="pending". Those docs are **invisible to retrieval** until a
human approves them — a guardrail against poisoning RAG with bad field notes.

This router is the curation queue's read/act surface:
- GET  /knowledge/pending             list docs awaiting review
- POST /knowledge/{id}/activate       approve -> is_active=True (enters retrieval)
- POST /knowledge/{id}/reject         reject  -> stays inactive, marked rejected

Sync PyMongo variant. Endpoints are plain `def` (FastAPI threadpools blocking
IO). Registered in api.py:

    from .routes_curation import router as curation_router
    app.include_router(curation_router)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .db import col

router = APIRouter(tags=["curation"])


def _strip_mongo_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("_id", None)
    return doc


class CurationAction(BaseModel):
    curator_id: Optional[str] = None
    reason: Optional[str] = None


@router.get("/knowledge/pending")
def list_pending_knowledge(
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Knowledge docs awaiting curator review (newest first)."""
    cursor = (
        col("knowledge_base")
        .find({"is_active": False, "curation_status": "pending"}, {"_id": 0})
        .sort("ingested_at_utc", -1)
        .limit(limit)
    )
    return [_strip_mongo_id(d) for d in cursor]


@router.post("/knowledge/{document_id}/activate")
def activate_knowledge(
    document_id: str, action: Optional[CurationAction] = None
) -> dict[str, Any]:
    """Approve a pending knowledge doc so it enters retrieval (is_active=True)."""
    doc = col("knowledge_base").find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(404, "knowledge document not found")
    if doc.get("is_active"):
        raise HTTPException(409, "knowledge document is already active")

    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {
        "is_active": True,
        "curation_status": "approved",
        "curated_at_utc": now,
    }
    if action and action.curator_id:
        update["curated_by"] = action.curator_id

    col("knowledge_base").update_one({"document_id": document_id}, {"$set": update})
    return _strip_mongo_id(col("knowledge_base").find_one({"document_id": document_id}))


@router.post("/knowledge/{document_id}/reject")
def reject_knowledge(
    document_id: str, action: Optional[CurationAction] = None
) -> dict[str, Any]:
    """Reject a pending knowledge doc — it stays inactive, marked rejected."""
    doc = col("knowledge_base").find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(404, "knowledge document not found")
    if doc.get("is_active"):
        raise HTTPException(409, "knowledge document is already active; cannot reject")

    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {
        "is_active": False,
        "curation_status": "rejected",
        "curated_at_utc": now,
    }
    if action and action.curator_id:
        update["curated_by"] = action.curator_id
    if action and action.reason:
        update["curation_reason"] = action.reason

    col("knowledge_base").update_one({"document_id": document_id}, {"$set": update})
    return _strip_mongo_id(col("knowledge_base").find_one({"document_id": document_id}))
