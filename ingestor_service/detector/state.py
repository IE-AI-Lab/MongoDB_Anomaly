"""
In-memory detector state.

This keeps track of "consecutive violating pings" per (sensor_id, metric).

Trade-off:
- In-memory state is simplest, but does not scale horizontally (each replica sees a different counter).
- Later, migrate this state to MongoDB or a shared cache so multiple ingestor replicas are consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class CounterState:
    """Consecutive-violation state for a single metric stream."""

    consecutive_violations: int = 0
    last_timestamp_utc: datetime | None = None


_STATE: dict[tuple[str, str], CounterState] = {}


def get_counter(sensor_id: str, metric_name: str) -> CounterState:
    """
    Return the counter state for (sensor_id, metric_name), creating it if missing.

    Key:
    - sensor_id: which sensor stream
    - metric_name: e.g. "temp_celsius", "amplitude_mm"
    """
    key = (sensor_id, metric_name)
    if key not in _STATE:
        _STATE[key] = CounterState()
    return _STATE[key]


def reset_all() -> None:
    """Clear all in-memory counters (useful for demo resets)."""
    _STATE.clear()

