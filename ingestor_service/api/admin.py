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

from fastapi import APIRouter
from pydantic import BaseModel

from ..messaging import queue
from ..core.db import col
from ..detector import state

router = APIRouter(tags=["admin"])

# system_metadata doc holding the simulator run/pause flag. The simulator polls
# GET /simulation/status each tick; start/stop flip this flag. Default running
# (the doc may not exist yet) so honcho start emits telemetry out of the box.
_SIM_CONTROL_FILTER: dict[str, Any] = {"config_type": "simulation_control"}


def _sim_running() -> bool:
    doc = col("system_metadata").find_one(_SIM_CONTROL_FILTER)
    if not doc:
        return True
    return bool(doc.get("running", True))


def _set_sim_running(running: bool) -> bool:
    col("system_metadata").update_one(
        _SIM_CONTROL_FILTER,
        {"$set": {
            "config_type": "simulation_control",
            "target_metric": "*",
            "running": running,
            "last_updated_by": "api/admin.py",
            "last_updated_at_utc": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    return running

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

    # Clear in-process detector debounce counters so a fresh run does not carry
    # over consecutive-violation state from the previous demo.
    state.reset_all()

    return {
        "deleted": deleted,
        "staff_reset": staff_result.modified_count,
        "redis_stream_trimmed": queue.trim_anomaly_stream(),
        "debounce_state_cleared": True,
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
    return {"running": _sim_running()}


@router.post("/simulation/start")
def simulation_start() -> dict[str, bool]:
    """Resume telemetry emission."""
    return {"running": _set_sim_running(True)}


@router.post("/simulation/stop")
def simulation_stop() -> dict[str, bool]:
    """Pause telemetry emission (the simulator process stays alive)."""
    return {"running": _set_sim_running(False)}
