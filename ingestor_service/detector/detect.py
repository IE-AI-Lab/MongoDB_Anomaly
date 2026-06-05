"""
Anomaly detection pipeline.

Given a newly persisted telemetry document, decide whether it triggers an anomaly.

Design constraints:
- Keep state in memory for now (consecutive violation counters).
- Build an anomaly document that matches the anomalies contract.
- If anomaly triggers, dispatch to the agent layer (stub or Redis queue).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from ..severity_engine import build_anomaly_severity_fields
from ..queue import dispatch_anomaly
from ..db import col
from .state import get_counter
from .thresholds import Threshold, get_threshold


def utc_now() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def _extract_metric_candidates(telemetry_doc: dict[str, Any]) -> list[tuple[str, float]]:
    """
    Extract numeric metric candidates from a telemetry_history document.

    Returns a list of (metric_name, value) pairs.

    Current convention:
    - Environment: temp_celsius, humidity_percent
    - Vibration: amplitude_mm
    - Pressure: pressure_bar
    - Flow: flow_rate_lpm
    """
    reading = telemetry_doc.get("reading", {}) or {}
    metric_type = reading.get("metric_type")

    pairs: list[tuple[str, float]] = []

    def add_if_present(name: str) -> None:
        if name in reading and isinstance(reading[name], (int, float)):
            pairs.append((name, float(reading[name])))

    if metric_type == "environment":
        add_if_present("temp_celsius")
        add_if_present("humidity_percent")
    elif metric_type == "vibration":
        add_if_present("amplitude_mm")
    elif metric_type == "pressure":
        add_if_present("pressure_bar")
    elif metric_type == "flow":
        add_if_present("flow_rate_lpm")

    return pairs


def _is_violation(value: float, threshold: Threshold) -> bool:
    """Return True if value violates the threshold's direction/limit."""
    if threshold.direction == "above":
        return value > threshold.limit
    return value < threshold.limit


def _error_code(metric_name: str, threshold: Threshold) -> str:
    """
    Map a violated metric to an error code.

    Keep this stable and enumerable: it becomes a join key into knowledge_base.
    """
    if metric_name == "temp_celsius":
        return "TEMP_HIGH" if threshold.direction == "above" else "TEMP_LOW"
    if metric_name == "humidity_percent":
        return "HUMIDITY_HIGH"
    if metric_name == "amplitude_mm":
        return "VIBRATION_HIGH"
    if metric_name == "pressure_bar":
        return "PRESSURE_LOW"
    if metric_name == "flow_rate_lpm":
        return "FLOW_LOW"
    return "METRIC_THRESHOLD_BREACH"


def process_telemetry(telemetry_doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Process one telemetry document and optionally create an anomaly.

    Flow:
    1) Identify candidate metrics from the telemetry reading.
    2) For each candidate metric, load the corresponding threshold rule.
    3) Update consecutive violation state for (sensor_id, metric_name).
    4) If consecutive_required is met, create an anomaly document and persist it.
    5) dispatch_anomaly(anomaly_doc) — stub or Redis stream.

    Returns:
    - The created anomaly document if triggered, otherwise None.
    """
    sensor_id = telemetry_doc.get("sensor_id")
    ts = telemetry_doc.get("timestamp_utc")
    if not sensor_id or not ts:
        return None

    facility_id = telemetry_doc.get("facility_id")
    equipment_id = telemetry_doc.get("equipment_id")
    reading = telemetry_doc.get("reading", {}) or {}
    metric_type = reading.get("metric_type")

    for metric_name, value in _extract_metric_candidates(telemetry_doc):
        threshold = get_threshold(sensor_id, metric_name)
        if not threshold:
            continue

        state = get_counter(sensor_id, metric_name)
        violated = _is_violation(value, threshold)
        state.last_timestamp_utc = ts

        if violated:
            state.consecutive_violations += 1
        else:
            state.consecutive_violations = 0
            continue

        if state.consecutive_violations < threshold.consecutive_required:
            continue

        # Trigger anomaly. Reset counter so we don't spam every tick.
        consecutive_count = state.consecutive_violations
        state.consecutive_violations = 0

        limit = threshold.limit
        direction = threshold.direction

        severity_fields = build_anomaly_severity_fields(
            observed=value, limit=limit, direction=direction
        )

        anomaly_id = f"ANOM-{uuid4()}"
        now = utc_now()

        anomaly_doc: dict[str, Any] = {
            "anomaly_id": anomaly_id,
            "timestamp_utc": ts,
            "sensor_id": sensor_id,
            "facility_id": facility_id,
            "equipment_id": equipment_id,
            "metric_type": metric_type,
            "error_code": _error_code(metric_name, threshold),
            **severity_fields,
            "trigger_value": {
                "metric": metric_name,
                "observed": value,
                "limit": limit,
                "unit": "si",
                "consecutive_count": consecutive_count,
            },
            "status": "unresolved",
            "created_at_utc": now,
            "updated_at_utc": now,
            "schema_version": 1,
        }

        col("anomalies").insert_one(anomaly_doc)

        # High-signal session event (optional but useful).
        col("session_events").insert_one(
            {
                "session_id": "default",
                "ts": now,
                "type": "anomaly_detected",
                "payload": {
                    "anomaly_id": anomaly_id,
                    "sensor_id": sensor_id,
                    "metric": metric_name,
                    "observed": value,
                    "limit": limit,
                    "severity_type": anomaly_doc["severity_type"],
                    "severity_level": anomaly_doc["severity_level"],
                },
            }
        )

        dispatch_anomaly(anomaly_doc)
        return anomaly_doc

    return None

