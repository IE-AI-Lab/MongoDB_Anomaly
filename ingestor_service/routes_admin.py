"""Admin endpoints — demo/MVP utilities. Currently: POST /simulation/reset.

Sync PyMongo variant. Endpoints are plain `def` (FastAPI threadpools blocking
IO). Registered in api.py:

    from .routes_admin import router as admin_router
    app.include_router(admin_router)

The reset purges runtime state (anomalies, telemetry, agent traces, session
events) and restores the full staff roster to on-call, while leaving seed data
(sensors, staff records, knowledge corpus, system_metadata) intact — so a demo
can restart from a clean slate without re-running scripts/init_db.py.

NOTE: this is a dev/MVP endpoint with no auth (like the rest of the API). If
auth lands, this is the first route that should require it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from . import queue
from .db import col

router = APIRouter(tags=["admin"])

# Collections holding runtime state — wiped entirely on reset. Seed-backed
# collections (sensors, staff_on_call, knowledge_base, system_metadata) are not
# listed here: staff is reset in place, knowledge is optionally pruned of
# feedback entries only.
_RUNTIME_COLLECTIONS: tuple[str, ...] = (
    "anomalies",
    "telemetry_history",
    "agent_execution_logs",
    "session_events",
)


class ResetRequest(BaseModel):
    # fb-* docs awaiting curation survive a reset unless explicitly purged.
    purge_feedback_knowledge: bool = False


@router.post("/simulation/reset")
def reset_simulation(req: ResetRequest) -> dict[str, Any]:
    """Purge runtime state for a fresh demo run. Seed data is untouched."""
    now = datetime.now(timezone.utc)

    deleted: dict[str, int] = {}
    for name in _RUNTIME_COLLECTIONS:
        deleted[name] = col(name).delete_many({}).deleted_count

    staff_result = col("staff_on_call").update_many(
        {}, {"$set": {"is_on_call": True, "updated_at_utc": now}}
    )

    deleted["knowledge_feedback"] = 0
    if req.purge_feedback_knowledge:
        deleted["knowledge_feedback"] = (
            col("knowledge_base")
            .delete_many({"document_id": {"$regex": "^fb-"}})
            .deleted_count
        )

    return {
        "deleted": deleted,
        "staff_reset": staff_result.modified_count,
        "redis_stream_trimmed": queue.trim_anomaly_stream(),
        "note": (
            "simulator sequence_number is in-process client state — "
            "restart the simulator to reset it"
        ),
    }
