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

from ..services.severity_engine import build_anomaly_severity_fields
from ..messaging.queue import dispatch_anomaly
from ..core import config
from ..core.db import col
from ..observability import record_anomaly_created
from .state import CounterState, get_counter
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


# --- metric naming for non-threshold detectors -------------------------------

_METRIC_BASE: dict[str, str] = {
    "temp_celsius": "TEMP",
    "humidity_percent": "HUMIDITY",
    "amplitude_mm": "VIBRATION",
    "pressure_bar": "PRESSURE",
    "flow_rate_lpm": "FLOW",
}


def _metric_base(metric_name: str) -> str:
    """Stable, enumerable prefix used to build error codes (e.g. TEMP)."""
    return _METRIC_BASE.get(metric_name, "METRIC")


# Primary alarm-bearing metric per metric_type (mirrors _extract_metric_candidates
# and the simulator's PROFILES). The manual "Trigger anomaly" button forces a
# breach on this metric.
_PRIMARY_METRIC: dict[str, str] = {
    "environment": "temp_celsius",
    "vibration": "amplitude_mm",
    "pressure": "pressure_bar",
    "flow": "flow_rate_lpm",
}

# Fallback limit/direction when no system_metadata threshold is configured for a
# metric (mirrors the seeded ball-mill thresholds in scripts/init_db.py).
_FALLBACK_THRESHOLD: dict[str, tuple[float, str]] = {
    "temp_celsius": (70.0, "above"),
    "humidity_percent": (80.0, "above"),
    "amplitude_mm": (7.1, "above"),
    "pressure_bar": (4.5, "below"),
    "flow_rate_lpm": (12.0, "below"),
}


# --- rate-of-change detector -------------------------------------------------

def _rate_of_change(prev: float, current: float, min_baseline: float) -> Optional[float]:
    """Fractional change vs the previous reading, or None if the baseline is
    too small to be meaningful (avoids divide-by-near-zero noise)."""
    if abs(prev) < min_baseline:
        return None
    return (current - prev) / abs(prev)


def _roc_error_code(metric_name: str, pct: float) -> str:
    base = _metric_base(metric_name)
    return f"{base}_RAPID_RISE" if pct >= 0 else f"{base}_RAPID_DROP"


# --- statistical (z-score) detector ------------------------------------------

def _zscore(baseline: list[float], current: float) -> tuple[float, float, float]:
    """Return (z, mean, std) of `current` vs the baseline window.

    z is 0.0 when the baseline has no spread (every reading identical), which
    correctly suppresses false positives on a flat signal."""
    n = len(baseline)
    mean = sum(baseline) / n
    variance = sum((x - mean) ** 2 for x in baseline) / n
    std = variance ** 0.5
    if std < 1e-9:
        return 0.0, mean, std
    return (current - mean) / std, mean, std


def _persist_and_dispatch(
    *,
    telemetry_doc: dict[str, Any],
    metric_name: str,
    value: float,
    error_code: str,
    detection_method: str,
    severity_fields: dict[str, Any],
    trigger_value: dict[str, Any],
) -> dict[str, Any]:
    """Build the anomaly document, persist it, emit metrics + a session event,
    and dispatch it to the agent layer. Shared by all three detectors."""
    now = utc_now()
    anomaly_id = f"ANOM-{uuid4()}"
    reading = telemetry_doc.get("reading", {}) or {}

    anomaly_doc: dict[str, Any] = {
        "anomaly_id": anomaly_id,
        "timestamp_utc": telemetry_doc.get("timestamp_utc"),
        "sensor_id": telemetry_doc.get("sensor_id"),
        "facility_id": telemetry_doc.get("facility_id"),
        "equipment_id": telemetry_doc.get("equipment_id"),
        "metric_type": reading.get("metric_type"),
        "error_code": error_code,
        "detection_method": detection_method,
        **severity_fields,
        "trigger_value": {"metric": metric_name, "observed": value, **trigger_value},
        "status": "unresolved",
        "created_at_utc": now,
        "updated_at_utc": now,
        "schema_version": 1,
    }

    col("anomalies").insert_one(anomaly_doc)
    record_anomaly_created(
        error_code=anomaly_doc["error_code"],
        metric_type=anomaly_doc.get("metric_type", ""),
        severity_type=anomaly_doc.get("severity_type", ""),
    )

    col("session_events").insert_one(
        {
            "session_id": "default",
            "ts": now,
            "type": "anomaly_detected",
            "payload": {
                "anomaly_id": anomaly_id,
                "sensor_id": anomaly_doc["sensor_id"],
                "metric": metric_name,
                "observed": value,
                "detection_method": detection_method,
                "severity_type": anomaly_doc["severity_type"],
                "severity_level": anomaly_doc["severity_level"],
            },
        }
    )

    dispatch_anomaly(anomaly_doc)
    return anomaly_doc


def create_manual_anomaly(
    sensor_doc: dict[str, Any], *, observed: Optional[float] = None
) -> dict[str, Any]:
    """Deterministically create + dispatch one threshold anomaly for a sensor.

    Bypasses the detector's debounce/arm state so it fires every time — this is
    the path behind the UI "Trigger anomaly" button. The result is shaped exactly
    like a real threshold breach (same fields, same dispatch path), so the agent
    and the anomaly lifecycle treat it identically. A single over-limit telemetry
    point is also persisted so the dashboard chart shows the spike even when the
    simulator is paused.
    """
    sensor_id = sensor_doc.get("sensor_id")
    if not sensor_id:
        raise ValueError("sensor_doc is missing sensor_id")

    metric_type = sensor_doc.get("metric_type", "")
    metric_name = _PRIMARY_METRIC.get(metric_type)
    if metric_name is None:
        raise ValueError(f"no primary metric known for metric_type {metric_type!r}")

    threshold = get_threshold(sensor_id, metric_name)
    if threshold is None:
        limit, direction = _FALLBACK_THRESHOLD[metric_name]
        threshold = Threshold(metric_name, direction, limit, 1)  # type: ignore[arg-type]

    # Deterministic over-limit value ~25% past the limit → "high" severity.
    if observed is None:
        factor = 1.25 if threshold.direction == "above" else 0.75
        observed = round(threshold.limit * factor, 4)

    now = utc_now()
    telemetry_doc: dict[str, Any] = {
        "timestamp_utc": now,
        "sensor_id": sensor_id,
        "facility_id": sensor_doc.get("facility_id"),
        "equipment_id": sensor_doc.get("equipment_id"),
        "ingested_at_utc": now,
        "source": "manual",
        "quality": "good",
        "reading": {
            "metric_type": metric_type,
            "unit_system": "si",
            metric_name: observed,
        },
        "event_id": f"manual-{uuid4()}",
    }
    # Persist the breach reading so the chart shows it immediately. Insert a copy
    # — a time-series insert mutates the doc with an _id we don't want downstream.
    col("telemetry_history").insert_one(dict(telemetry_doc))

    # Mirror a real detector fire: disarm the threshold counter so the breach the
    # simulator now sustains (it holds any sensor with an open anomaly) doesn't
    # produce a *second*, detector-created anomaly. It re-arms when a reading
    # returns to the normal side of the limit.
    counter = get_counter(sensor_id, metric_name)
    counter.threshold_armed = False
    counter.consecutive_violations = max(
        counter.consecutive_violations, threshold.consecutive_required
    )

    severity_fields = build_anomaly_severity_fields(
        observed=observed, limit=threshold.limit, direction=threshold.direction
    )
    return _persist_and_dispatch(
        telemetry_doc=telemetry_doc,
        metric_name=metric_name,
        value=observed,
        error_code=_error_code(metric_name, threshold),
        detection_method="threshold",
        severity_fields=severity_fields,
        trigger_value={
            "limit": threshold.limit,
            "unit": "si",
            "consecutive_count": threshold.consecutive_required,
        },
    )


def _check_threshold(
    telemetry_doc: dict[str, Any],
    metric_name: str,
    value: float,
    threshold: Threshold,
    state: CounterState,
) -> Optional[dict[str, Any]]:
    """Static threshold detector with consecutive-violation debounce.

    Once it fires, the detector disarms and stays silent for the rest of the
    breach episode — a value that climbs over the limit and is *held* there
    (until a worker resolves the anomaly) produces exactly one anomaly, not one
    per reading. It re-arms only when a reading returns to the normal side of
    the limit. Mirrors the roc_armed / stat_armed pattern of the other two
    detectors.
    """
    if not _is_violation(value, threshold):
        state.consecutive_violations = 0
        state.threshold_armed = True  # back to normal → re-arm for the next episode
        return None

    state.consecutive_violations += 1
    if state.consecutive_violations < threshold.consecutive_required:
        return None

    if not state.threshold_armed:
        return None  # ongoing breach already reported; stay silent until recovery
    state.threshold_armed = False

    consecutive_count = state.consecutive_violations

    severity_fields = build_anomaly_severity_fields(
        observed=value, limit=threshold.limit, direction=threshold.direction
    )
    return _persist_and_dispatch(
        telemetry_doc=telemetry_doc,
        metric_name=metric_name,
        value=value,
        error_code=_error_code(metric_name, threshold),
        detection_method="threshold",
        severity_fields=severity_fields,
        trigger_value={
            "limit": threshold.limit,
            "unit": "si",
            "consecutive_count": consecutive_count,
        },
    )


def _check_rate_of_change(
    telemetry_doc: dict[str, Any],
    metric_name: str,
    value: float,
    prev: float,
    state: CounterState,
) -> Optional[dict[str, Any]]:
    """Fire when a reading jumps too far from the previous one — catches fast
    excursions that are still within static limits."""
    pct = _rate_of_change(prev, value, config.roc_min_baseline())
    if pct is None:
        return None

    limit = config.roc_pct_threshold()
    if abs(pct) < limit:
        state.roc_armed = True  # back to normal → re-arm
        return None

    if not state.roc_armed:
        return None  # already reported this excursion
    state.roc_armed = False

    severity_fields = build_anomaly_severity_fields(
        observed=abs(pct), limit=limit, direction="above"
    )
    return _persist_and_dispatch(
        telemetry_doc=telemetry_doc,
        metric_name=metric_name,
        value=value,
        error_code=_roc_error_code(metric_name, pct),
        detection_method="rate_of_change",
        severity_fields=severity_fields,
        trigger_value={
            "previous": prev,
            "pct_change": round(pct, 4),
            "pct_threshold": limit,
        },
    )


def _check_statistical(
    telemetry_doc: dict[str, Any],
    metric_name: str,
    value: float,
    baseline: list[float],
    state: CounterState,
) -> Optional[dict[str, Any]]:
    """Fire when a reading is a statistical outlier vs the rolling baseline."""
    z, mean, std = _zscore(baseline, value)
    limit = config.statistical_zscore()
    if abs(z) < limit:
        state.stat_armed = True  # back within normal spread → re-arm
        return None

    if not state.stat_armed:
        return None
    state.stat_armed = False

    severity_fields = build_anomaly_severity_fields(
        observed=abs(z), limit=limit, direction="above"
    )
    return _persist_and_dispatch(
        telemetry_doc=telemetry_doc,
        metric_name=metric_name,
        value=value,
        error_code=f"{_metric_base(metric_name)}_OUTLIER",
        detection_method="statistical",
        severity_fields=severity_fields,
        trigger_value={
            "z_score": round(z, 4),
            "z_threshold": limit,
            "baseline_mean": round(mean, 4),
            "baseline_std": round(std, 4),
            "baseline_size": len(baseline),
        },
    )


def process_telemetry(telemetry_doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Process one telemetry document and optionally create an anomaly.

    Three detectors run per candidate metric, in priority order. The first to
    fire wins (one anomaly per telemetry document):

    1) threshold      — value crosses a static limit for N consecutive readings.
    2) rate-of-change — value jumps too far from the previous reading
                        (env-gated: ANOMALY_ROC_ENABLED).
    3) statistical    — value is a z-score outlier vs the rolling baseline
                        (env-gated: ANOMALY_STAT_ENABLED).

    The rolling window is updated for every reading regardless of which (if any)
    detector fires, so the rate-of-change and statistical baselines stay warm.

    Returns the created anomaly document if triggered, otherwise None.
    """
    sensor_id = telemetry_doc.get("sensor_id")
    ts = telemetry_doc.get("timestamp_utc")
    if not sensor_id or not ts:
        return None

    window_size = config.anomaly_window_size()
    roc_on = config.roc_enabled()
    stat_on = config.statistical_enabled()
    stat_min = config.statistical_min_readings()

    for metric_name, value in _extract_metric_candidates(telemetry_doc):
        state = get_counter(sensor_id, metric_name)
        state.last_timestamp_utc = ts

        # Snapshot the window *before* this reading is appended, so the
        # rate-of-change/statistical baselines exclude the current value.
        window_before = list(state.values)
        state.push(value, window_size)

        # 1) Static threshold (unchanged behavior; only runs when a rule exists).
        threshold = get_threshold(sensor_id, metric_name)
        if threshold:
            anomaly = _check_threshold(telemetry_doc, metric_name, value, threshold, state)
            if anomaly is not None:
                return anomaly

        # 2) Rate-of-change (needs at least one prior reading).
        if roc_on and window_before:
            anomaly = _check_rate_of_change(
                telemetry_doc, metric_name, value, window_before[-1], state
            )
            if anomaly is not None:
                return anomaly

        # 3) Statistical outlier (needs a warm baseline).
        if stat_on and len(window_before) >= stat_min:
            anomaly = _check_statistical(
                telemetry_doc, metric_name, value, window_before, state
            )
            if anomaly is not None:
                return anomaly

    return None

