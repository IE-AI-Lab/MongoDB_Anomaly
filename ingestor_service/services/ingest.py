"""
Telemetry ingestion helpers.

Responsibilities:
- Convert validated API events into MongoDB-ready documents.
- Persist telemetry into `telemetry_history`.
- Return data needed for anomaly detection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core.db import col
from ..models import TelemetryIngestEvent


def utc_now() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def to_telemetry_document(event: TelemetryIngestEvent) -> dict[str, Any]:
    """
    Convert a TelemetryIngestEvent into the canonical MongoDB document shape used by telemetry_history.

    Notes:
    - `timestamp_utc` is the sensor timestamp; `ingested_at_utc` is when our service received it.
    - The time-series collection uses (timestamp_utc, sensor_id) as (timeField, metaField).
    - `reading` is stored as a polymorphic object with `metric_type` plus a flexible data payload.
    """
    return {
        "timestamp_utc": event.timestamp_utc,
        "sensor_id": event.sensor_id,
        "facility_id": event.facility_id,
        "equipment_id": event.equipment_id,
        "ingested_at_utc": utc_now(),
        "source": event.source,
        "quality": event.quality,
        "sequence_number": event.sequence_number,
        "reading": {
            "metric_type": event.reading.metric_type,
            "unit_system": event.reading.unit_system,
            **event.reading.data,
        },
        "event_id": event.event_id,
    }


def persist_telemetry(event: TelemetryIngestEvent) -> dict[str, Any]:
    """
    Persist one telemetry event into the time-series collection.

    Returns:
    - The inserted telemetry document (without MongoDB _id because time-series inserts can be high volume
      and callers usually don't need the _id).
    """
    doc = to_telemetry_document(event)
    col("telemetry_history").insert_one(doc)
    return doc

