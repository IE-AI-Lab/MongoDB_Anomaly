"""Write endpoints — agent commits analysis, manager assigns, staff resolves.

Sync PyMongo variant. Endpoints are plain `def` (FastAPI threadpools blocking
IO). Mounted via api/__init__.py's `all_routers`.

Depends on: services/feedback_to_knowledge.py (closed RAG loop).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.db import col
from ..services.feedback_to_knowledge import embed_resolution_into_knowledge

router = APIRouter(tags=["write"])


# Anomaly status lifecycle: unresolved -> analyzed -> assigned -> resolved.
# These ranks let us enforce forward-only transitions. `assigned` and `resolved`
# are reachable ONLY through their dedicated endpoints (which carry side effects:
# flipping staff on-call state and closing the RAG loop), never via a raw PATCH.
VALID_STATUSES: tuple[str, ...] = ("unresolved", "analyzed", "assigned", "resolved")
_STATUS_RANK: dict[str, int] = {s: i for i, s in enumerate(VALID_STATUSES)}


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

    current = col("anomalies").find_one({"anomaly_id": anomaly_id})
    if not current:
        raise HTTPException(404, "anomaly not found")

    new_status = update.get("status")
    if new_status is not None:
        cur_status = current.get("status", "unresolved")
        if new_status not in _STATUS_RANK:
            raise HTTPException(400, f"invalid status '{new_status}'; must be one of {VALID_STATUSES}")
        if new_status in ("assigned", "resolved"):
            raise HTTPException(
                409,
                f"cannot set status '{new_status}' via PATCH — use "
                f"POST /anomalies/{{id}}/assign or /resolve (they carry side effects)",
            )
        if cur_status == "resolved":
            raise HTTPException(409, "anomaly is resolved (terminal); cannot change status")
        if _STATUS_RANK[new_status] < _STATUS_RANK[cur_status]:
            raise HTTPException(409, f"cannot move status backward: {cur_status} -> {new_status}")

    update["updated_at_utc"] = datetime.now(timezone.utc)
    col("anomalies").update_one({"anomaly_id": anomaly_id}, {"$set": update})
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

    cur_status = anomaly.get("status", "unresolved")
    if cur_status == "resolved":
        raise HTTPException(409, "anomaly is resolved (terminal); cannot assign")
    if cur_status == "assigned":
        raise HTTPException(
            409,
            f"anomaly already assigned to {anomaly.get('assigned_to_employee_id')}",
        )

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
    if anomaly.get("status") == "resolved":
        raise HTTPException(409, "anomaly is already resolved")

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
