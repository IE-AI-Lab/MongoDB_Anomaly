"""Read endpoints the agent calls to gather context for an anomaly.

Sync PyMongo variant. Endpoints are plain `def` — FastAPI runs sync handlers
in a threadpool, which is correct for blocking PyMongo IO.

Registered in api.py:

    from .routes_read import router as read_router
    app.include_router(read_router)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from .db import col
from .rag import search_knowledge

router = APIRouter(tags=["read"])


def _strip_mongo_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("_id", None)
    return doc


@router.get("/anomalies/{anomaly_id}")
def get_anomaly(anomaly_id: str) -> dict[str, Any]:
    doc = col("anomalies").find_one({"anomaly_id": anomaly_id})
    if not doc:
        raise HTTPException(404, "anomaly not found")
    return _strip_mongo_id(doc)


@router.get("/anomalies")
def list_anomalies(
    status: Optional[str] = Query(
        None, description="unresolved / analyzed / assigned / resolved"
    ),
    sensor_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if sensor_id:
        q["sensor_id"] = sensor_id
    cursor = col("anomalies").find(q).sort("timestamp_utc", -1).limit(limit)
    return [_strip_mongo_id(d) for d in cursor]


@router.get("/sensors/{sensor_id}")
def get_sensor(sensor_id: str) -> dict[str, Any]:
    doc = col("sensors").find_one({"sensor_id": sensor_id})
    if not doc:
        raise HTTPException(404, "sensor not found")
    return _strip_mongo_id(doc)


@router.get("/sensors/{sensor_id}/readings")
def recent_readings(
    sensor_id: str,
    minutes: int = Query(60, ge=1, le=24 * 60),
    limit: int = Query(200, ge=1, le=2000),
) -> list[dict[str, Any]]:
    """Recent telemetry from the time-series collection."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    cursor = (
        col("telemetry_history")
        .find({"sensor_id": sensor_id, "timestamp_utc": {"$gte": since}})
        .sort("timestamp_utc", 1)
        .limit(limit)
    )
    return [_strip_mongo_id(r) for r in cursor]


@router.get("/knowledge/search")
def knowledge_search(
    q: str = Query(..., min_length=1, description="natural language query"),
    equipment_type: Optional[str] = None,
    error_codes: Optional[str] = Query(
        None, description="comma-separated error codes, e.g. VIBRATION_HIGH,BEARING_WEAR"
    ),
    k: int = Query(5, ge=1, le=20),
) -> list[dict[str, Any]]:
    """Vector search wrapper. Agent calls this from its analyze node."""
    codes = [c.strip() for c in error_codes.split(",")] if error_codes else None
    return search_knowledge(q, equipment_type=equipment_type, error_codes=codes, k=k)


@router.get("/staff_on_call")
def list_on_call(
    is_on_call: Optional[bool] = None,
    specialization: Optional[str] = Query(None, description="single tag, e.g. vibration"),
    handled_severity_type: Optional[str] = Query(None, description="low / medium / high"),
    facility_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Staff filter for the agent's recommend node and the manager UI."""
    q: dict[str, Any] = {"is_active": True}
    if is_on_call is not None:
        q["is_on_call"] = is_on_call
    if specialization:
        q["specialization"] = specialization
    if handled_severity_type:
        q["handled_severity_type"] = handled_severity_type
    if facility_id:
        q["facility_ids"] = facility_id
    cursor = col("staff_on_call").find(q).sort("escalation_rank", 1)
    return [_strip_mongo_id(s) for s in cursor]
