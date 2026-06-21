"""Admin endpoints — demo/MVP utilities. Currently: POST /simulation/reset.

Sync PyMongo variant. Endpoints are plain `def` (FastAPI threadpools blocking
IO). Mounted via api/__init__.py's `all_routers`.

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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..messaging import queue
from ..core.db import col
from ..detector import state
from ..services import simulation_control

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


@router.get("/queues/status")
def queues_status() -> dict[str, Any]:
    """Per-severity stream depths + DLQ count for the dashboard queue panel."""
    return queue.stream_depths()


@router.post("/queues/reset")
def reset_queues() -> dict[str, Any]:
    """Wipe Redis anomaly streams only (high/medium/low + dlq). Mongo untouched."""
    return queue.reset_anomaly_streams()


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

    # Clear in-process detector debounce counters so a fresh run does not carry
    # over consecutive-violation state from the previous demo.
    state.reset_all()

    return {
        "deleted": deleted,
        "staff_reset": staff_result.modified_count,
        "debounce_state_cleared": True,
        # Per-severity streams + DLQ are wiped and the consumer groups recreated.
        "redis_streams": queue.reset_anomaly_streams(),
        "note": (
            "simulator sequence_number is in-process client state — "
            "restart the simulator to reset it"
        ),
    }


# ---------------------------------------------------------------------------
# Simulation run/pause control — UI Start/Stop buttons; simulator polls status
# ---------------------------------------------------------------------------


@router.get("/simulation/status")
def simulation_status() -> dict[str, bool]:
    """Current run state. The simulator polls this each tick (fail-open to running)."""
    return {"running": simulation_control.is_running()}


@router.post("/simulation/start")
def simulation_start() -> dict[str, bool]:
    """Resume telemetry emission."""
    return {"running": simulation_control.set_running(True)}


@router.post("/simulation/stop")
def simulation_stop() -> dict[str, bool]:
    """Pause telemetry emission (the simulator process stays alive)."""
    return {"running": simulation_control.set_running(False)}


# ---------------------------------------------------------------------------
# Per-machine degradation rate — the dashboard "stress" slider; the simulator
# reads sim_stress off each sensor each cycle to set how fast its signal climbs
# toward the alarm (0 = healthy/flat, 1 = steep climb → frequent anomalies).
# ---------------------------------------------------------------------------


class StressRequest(BaseModel):
    sim_stress: float = Field(..., ge=0.0, le=1.0)


@router.post("/simulation/sensors/{sensor_id}/stress")
def set_sensor_stress(sensor_id: str, req: StressRequest) -> dict[str, Any]:
    """Set a sensor's simulator degradation rate (0..1). Read back via GET /sensors."""
    now = datetime.now(timezone.utc)
    result = col("sensors").update_one(
        {"sensor_id": sensor_id},
        {"$set": {"sim_stress": req.sim_stress, "updated_at_utc": now}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "sensor not found")
    return {"sensor_id": sensor_id, "sim_stress": req.sim_stress}
