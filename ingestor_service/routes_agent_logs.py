"""Agent run-trace endpoints — the agent worker POSTs its execution traces here.

Sync PyMongo variant. Endpoints are plain `def` (FastAPI threadpools blocking
IO). Registered in api.py:

    from .routes_agent_logs import router as agent_logs_router
    app.include_router(agent_logs_router)

Why an endpoint (and not the worker writing Mongo directly)? The agent worker is
a decoupled process that talks to the data layer over HTTP only (see
docs/AGENT_TEAM_GUIDE.md §6.2). This is the write path for `agent_execution_logs`
— the collection, indexes (`run_id` unique, `anomaly_id`+`started_at`) and the
document contract already exist (scripts/init_db.py); this just exposes it.

The document contract is the one documented in scripts/init_db.py. POST is an
upsert keyed by `run_id`, so the worker can write a "running" record at the start
of a graph run and overwrite it with the "completed"/"failed" record at the end.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .db import col

router = APIRouter(tags=["agent-logs"])

VALID_RUN_STATUSES: tuple[str, ...] = ("running", "completed", "failed")


def _strip_mongo_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("_id", None)
    return doc


class ExecutionStep(BaseModel):
    step_index: int
    tool_name: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    input_summary: Optional[dict] = None
    output_summary: Optional[dict] = None
    success: Optional[bool] = None
    latency_ms: Optional[int] = None


class TokensUsed(BaseModel):
    prompt: int = 0
    completion: int = 0
    total: int = 0
    embedding: int = 0


class AgentLogUpsert(BaseModel):
    run_id: str
    anomaly_id: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "running"  # running / completed / failed
    agent_name: Optional[str] = None
    agent_version: Optional[str] = None
    model_id: Optional[str] = None
    execution_steps: Optional[list[ExecutionStep]] = None
    final_action_taken: Optional[str] = None
    tokens_used: Optional[TokensUsed] = None
    error: Optional[dict] = None
    correlation_id: Optional[str] = None


@router.post("/agent_logs")
def upsert_agent_log(log: AgentLogUpsert) -> dict[str, Any]:
    """Create or update one agent run trace (upsert keyed by run_id)."""
    if log.status not in VALID_RUN_STATUSES:
        raise HTTPException(
            400, f"invalid status '{log.status}'; must be one of {VALID_RUN_STATUSES}"
        )

    now = datetime.now(timezone.utc)
    # Only persist fields the caller actually set, so a "completed" update does
    # not blank out values written by the earlier "running" record.
    update = {k: v for k, v in log.model_dump(exclude_unset=True).items() if v is not None}

    existing = col("agent_execution_logs").find_one({"run_id": log.run_id})
    if existing:
        col("agent_execution_logs").update_one(
            {"run_id": log.run_id}, {"$set": update}
        )
    else:
        update.setdefault("started_at", now)
        col("agent_execution_logs").insert_one(update)

    return _strip_mongo_id(
        col("agent_execution_logs").find_one({"run_id": log.run_id})
    )


@router.get("/agent_logs")
def list_agent_logs(
    anomaly_id: Optional[str] = None,
    run_id: Optional[str] = None,
    status: Optional[str] = Query(None, description="running / completed / failed"),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Read run traces — for the observability dashboard and debugging."""
    q: dict[str, Any] = {}
    if anomaly_id:
        q["anomaly_id"] = anomaly_id
    if run_id:
        q["run_id"] = run_id
    if status:
        q["status"] = status
    cursor = col("agent_execution_logs").find(q).sort("started_at", -1).limit(limit)
    return [_strip_mongo_id(d) for d in cursor]
