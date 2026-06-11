"""
Threshold lookup logic.

This module answers: given a metric name, what limit should we compare against,
and how many consecutive violations are required to trigger?

Hybrid rules:
- system_metadata holds global defaults (required).
- sensors can optionally hold per-sensor overrides (future; not required today).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..core.db import col


Direction = Literal["above", "below"]


@dataclass(frozen=True)
class Threshold:
    """A normalized threshold spec for a single metric."""

    metric_name: str
    direction: Direction
    limit: float
    consecutive_required: int


def _load_global_threshold(metric_name: str) -> dict[str, Any] | None:
    """
    Load the system_metadata anomaly_thresholds document for a metric.

    Schema shape is intentionally flexible; we support the seeded keys from scripts/init_db.py.
    """
    return col("system_metadata").find_one(
        {"config_type": "anomaly_thresholds", "target_metric": metric_name, "is_enabled": True}
    )


def get_threshold(sensor_id: str, metric_name: str) -> Threshold | None:
    """
    Return the threshold for (sensor_id, metric_name) or None if no rule exists.

    Current behavior:
    - Uses only global rules from system_metadata.

    Future extension:
    - Check sensors collection for per-sensor overrides.
    """
    doc = _load_global_threshold(metric_name)
    if not doc:
        return None

    rules = doc.get("rules", {})
    consecutive = int(rules.get("consecutive_violating_pings_required", 3))

    # Convention: metrics can have min and/or max.
    # For v1 we assume a single direction per metric name:
    if metric_name == "temp_celsius":
        limit = float(rules.get("max_allowed_temp_celsius"))
        return Threshold(metric_name, "above", limit, consecutive)

    if metric_name == "humidity_percent":
        limit = float(rules.get("max_allowed_humidity_percent"))
        return Threshold(metric_name, "above", limit, consecutive)

    if metric_name == "amplitude_mm":
        limit = float(rules.get("max_allowed_amplitude_mm"))
        return Threshold(metric_name, "above", limit, consecutive)

    if metric_name == "pressure_bar":
        # treat pressure low as the anomaly for demo (below min)
        limit = float(rules.get("min_allowed_pressure_bar"))
        return Threshold(metric_name, "below", limit, consecutive)

    if metric_name == "flow_rate_lpm":
        limit = float(rules.get("min_allowed_flow_rate_lpm"))
        return Threshold(metric_name, "below", limit, consecutive)

    return None

