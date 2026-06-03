"""
Pydantic models for API boundary validation.

These models define the *ingestion contract* between simulator and ingestor.
MongoDB itself does not enforce these shapes; validating at the API boundary
prevents silent schema drift (typos, missing fields, wrong types).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


Quality = Literal["good", "suspect", "bad"]
MetricType = Literal["environment", "vibration", "pressure", "flow"]


class TelemetryReading(BaseModel):
    """
    Polymorphic reading payload.

    The only enforced discriminator is `metric_type`. Other fields are
    intentionally flexible because real sensors differ and this is a simulator-driven project.
    """

    metric_type: MetricType
    unit_system: Optional[str] = "si"

    # sensor-type-specific numeric fields live here (flexible)
    data: dict[str, Any] = Field(default_factory=dict)


class TelemetryIngestEvent(BaseModel):
    """
    One telemetry event produced by the simulator.

    Key design decisions:
    - `event_id` allows deduplication/idempotency later.
    - `sequence_number` is per-sensor monotonic ordering (helps detect duplicates/gaps).
    - `timestamp_utc` is the time the sensor reading was taken (not ingestion time).
    """

    event_id: str
    timestamp_utc: datetime
    sensor_id: str

    facility_id: Optional[str] = None
    equipment_id: Optional[str] = None

    source: str = "simulator"
    quality: Quality = "good"
    sequence_number: int = 0

    reading: TelemetryReading


class IngestResponse(BaseModel):
    """API response after ingesting one telemetry event."""

    stored: bool
    anomaly_created: bool
    anomaly_id: Optional[str] = None

