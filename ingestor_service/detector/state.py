"""
In-memory detector state.

This keeps track of "consecutive violating pings" per (sensor_id, metric).

Trade-off:
- In-memory state is simplest, but does not scale horizontally (each replica sees a different counter).
- Later, migrate this state to MongoDB or a shared cache so multiple ingestor replicas are consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CounterState:
    """Per-metric detector state for a single (sensor_id, metric) stream.

    Holds three independent detectors' state:
    - threshold:        consecutive_violations counter (debounce)
    - rate-of-change:   the rolling window + a re-arm flag
    - statistical:      the rolling window + a re-arm flag

    The re-arm flags prevent a single sustained excursion from emitting an
    anomaly on every subsequent reading: once a detector fires it is disarmed
    until a reading returns to normal, then it re-arms.
    """

    consecutive_violations: int = 0
    last_timestamp_utc: datetime | None = None
    # Rolling window of the most recent values (count-based, not time-based —
    # the pipeline runs intermittently, so "last N readings" is more reliable
    # than "last N minutes").
    values: list[float] = field(default_factory=list)
    roc_armed: bool = True
    stat_armed: bool = True

    def push(self, value: float, max_size: int) -> None:
        """Append a reading to the rolling window, evicting the oldest."""
        self.values.append(value)
        if max_size > 0:
            while len(self.values) > max_size:
                self.values.pop(0)


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

