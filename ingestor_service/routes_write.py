"""Write endpoints — agent commits analysis, manager assigns, staff resolves.

Sync PyMongo variant. Endpoints are plain `def` (FastAPI threadpools blocking
IO). Registered in api.py:

    from .routes_write import router as write_router
    app.include_router(write_router)

Depends on: ingestor_service/feedback_to_knowledge.py (step 07).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .db import col
from .feedback_to_knowledge import embed_resolution_into_knowledge

router = APIRouter(tags=["write"])


def _strip_mongo_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Agent → commits analysis + recommendation back onto the anomaly doc
# ---------------------------------------------------------------------------

class AnalysisPatch(BaseModel):
    description: Optional[str] = None
    recommended_solution: Optional[str] = None
    similar_cases: Optional[list[dict]] = None
    recommended_employee_id: Optional[str] = None
    agent_run_id: Optional[str] = None
    status: Optional[str] = None  # typically "analyzed"


@router.patch("/anomalies/{anomaly_id}")
def patch_anomaly(anomaly_id: str, patch: AnalysisPatch) -> dict[str, Any]:
    """Agent writes its analysis here when graph execution completes."""
    update = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(400, "no fields to update")
    update["updated_at_utc"] = datetime.now(timezone.utc)

    res = col("anomalies").update_one({"anomaly_id": anomaly_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "anomaly not found")

    return _strip_mongo_id(col("anomalies").find_one({"anomaly_id": anomaly_id}))


# ---------------------------------------------------------------------------
# Manager → assigns an on-call staff member to an anomaly
# ---------------------------------------------------------------------------

class AssignRequest(BaseModel):
    employee_id: str


@router.post("/anomalies/{anomaly_id}/assign")
def assign_anomaly(anomaly_id: str, req: AssignRequest) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    anomaly = col("anomalies").find_one({"anomaly_id": anomaly_id})
    if not anomaly:
        raise HTTPException(404, "anomaly not found")
    staff = col("staff_on_call").find_one({"employee_id": req.employee_id})
    if not staff:
        raise HTTPException(404, "employee not found")
    if not staff.get("is_on_call", False):
        raise HTTPException(409, "employee is not on call")

    col("anomalies").update_one(
        {"anomaly_id": anomaly_id},
        {"$set": {
            "assigned_to_employee_id": req.employee_id,
            "status": "assigned",
            "updated_at_utc": now,
        }},
    )
    col("staff_on_call").update_one(
        {"employee_id": req.employee_id},
        {"$set": {"is_on_call": False, "updated_at_utc": now}},
    )
    return _strip_mongo_id(col("anomalies").find_one({"anomaly_id": anomaly_id}))


# ---------------------------------------------------------------------------
# Staff → resolves with feedback; closes the RAG loop on success
# ---------------------------------------------------------------------------

class ResolveRequest(BaseModel):
    outcome: str  # "fixed" / "false_positive" / "deferred"
    resolution_notes: str
    resolved_by: Optional[str] = None  # employee_id; defaults to current assignee


@router.post("/anomalies/{anomaly_id}/resolve")
def resolve_anomaly(anomaly_id: str, req: ResolveRequest) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    anomaly = col("anomalies").find_one({"anomaly_id": anomaly_id})
    if not anomaly:
        raise HTTPException(404, "anomaly not found")

    resolver = req.resolved_by or anomaly.get("assigned_to_employee_id")

    col("anomalies").update_one(
        {"anomaly_id": anomaly_id},
        {"$set": {
            "status": "resolved",
            "resolution_notes": req.resolution_notes,
            "resolved_by": resolver,
            "resolved_at_utc": now,
            "updated_at_utc": now,
        }},
    )
    if resolver:
        col("staff_on_call").update_one(
            {"employee_id": resolver},
            {"$set": {"is_on_call": True, "updated_at_utc": now}},
        )

    # Closed RAG loop — only useful resolutions get embedded back.
    new_doc_id: Optional[str] = None
    if req.outcome == "fixed":
        new_doc_id = embed_resolution_into_knowledge(
            anomaly_id=anomaly_id,
            anomaly=anomaly,
            resolution_notes=req.resolution_notes,
            resolved_by=resolver,
        )

    out = _strip_mongo_id(col("anomalies").find_one({"anomaly_id": anomaly_id}))
    if new_doc_id:
        out["knowledge_document_id"] = new_doc_id
    return out
