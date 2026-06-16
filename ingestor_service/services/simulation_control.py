"""Simulation run/pause control — the one home for the simulator's run/pause flag.

The flag is a single `system_metadata` document (`config_type="simulation_control"`).
The simulator polls `GET /simulation/status` each tick (fail-open to running); the
UI Start/Stop buttons flip it via `POST /simulation/start|stop`. Both the API
router (`api/admin.py`) and the DB seeder (`scripts/init_db.py`) reference the
document shape from here, so the schema lives in exactly one place.

Fail-open is deliberate: a missing/unreadable doc means "running", so a fresh DB
or a control-plane hiccup keeps telemetry flowing rather than silently freezing.

Sync PyMongo variant (matches the rest of this service).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core.db import col

CONFIG_TYPE = "simulation_control"

# Mongo filter uniquely identifying the control doc.
FILTER: dict[str, Any] = {"config_type": CONFIG_TYPE}

# Value when the doc is absent or has no `running` field — see module docstring.
DEFAULT_RUNNING = True


def control_document(running: bool = DEFAULT_RUNNING, *, updated_by: str) -> dict[str, Any]:
    """Canonical field shape for the control doc.

    Shared by the API writer (`set_running`) and the DB seeder so the schema is
    defined once. `target_metric="*"` mirrors the other `system_metadata` docs.
    """
    return {
        "config_type": CONFIG_TYPE,
        "target_metric": "*",
        "running": running,
        "last_updated_by": updated_by,
        "last_updated_at_utc": datetime.now(timezone.utc),
    }


def is_running() -> bool:
    """Whether the simulator should currently emit. Fail-open to running."""
    doc = col("system_metadata").find_one(FILTER)
    if not doc:
        return DEFAULT_RUNNING
    return bool(doc.get("running", DEFAULT_RUNNING))


def set_running(running: bool, *, updated_by: str = "api/admin.py") -> bool:
    """Persist the run/pause flag, creating the doc if absent. Returns `running`."""
    col("system_metadata").update_one(
        FILTER,
        {"$set": control_document(running, updated_by=updated_by)},
        upsert=True,
    )
    return running
