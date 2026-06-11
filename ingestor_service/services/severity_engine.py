"""
Map a threshold breach to severity_level (1-10) and severity_type (low/medium/high).

Breach ratio examples (limit above, observed 100, max 80):
    ratio = (100 - 80) / 80 = 0.25  ->  high, level 10

Load bands from system_metadata config_type "severity_bands" in production;
defaults below match the seeded document in scripts/init_db.py.
"""

from __future__ import annotations

from typing import Literal, TypedDict

SeverityType = Literal["low", "medium", "high"]


class SeverityBands(TypedDict):
    low_max_ratio: float
    medium_max_ratio: float


DEFAULT_BANDS: SeverityBands = {
    "low_max_ratio": 0.10,
    "medium_max_ratio": 0.25,
}


def breach_ratio(observed: float, limit: float, direction: Literal["above", "below"]) -> float:
    """Return how far past the limit the observation is, as a fraction of the limit."""
    if limit == 0:
        raise ValueError("limit must be non-zero")

    if direction == "above":
        if observed <= limit:
            return 0.0
        return (observed - limit) / abs(limit)

    if observed >= limit:
        return 0.0
    return (limit - observed) / abs(limit)


def compute_severity(
    observed: float,
    limit: float,
    direction: Literal["above", "below"] = "above",
    bands: SeverityBands | None = None,
) -> tuple[int, SeverityType]:
    """
    Return (severity_level, severity_type) for a single reading vs one limit.

    - low:    ratio < low_max_ratio     -> levels 1-3  (common simulator noise)
    - medium: ratio < medium_max_ratio  -> levels 4-7
    - high:   ratio >= medium_max_ratio -> levels 8-10 (rare, large breaches)
    """
    active_bands = bands or DEFAULT_BANDS
    ratio = breach_ratio(observed, limit, direction)

    if ratio <= 0:
        return 1, "low"

    low_cap = active_bands["low_max_ratio"]
    medium_cap = active_bands["medium_max_ratio"]

    if ratio < low_cap:
        level = _scale_level(ratio, 0.0, low_cap, 1, 3)
        return level, "low"

    if ratio < medium_cap:
        level = _scale_level(ratio, low_cap, medium_cap, 4, 7)
        return level, "medium"

    # At or above the medium band (e.g. 100 C vs 80 C max -> ratio 0.25) -> high, level 10.
    level = _scale_level(ratio, medium_cap, medium_cap * 2, 9, 10)
    return max(level, 10), "high"


def _scale_level(value: float, low: float, high: float, out_min: int, out_max: int) -> int:
    if high <= low:
        return out_max
    fraction = min(max((value - low) / (high - low), 0.0), 1.0)
    return round(out_min + fraction * (out_max - out_min))


def build_anomaly_severity_fields(
    observed: float,
    limit: float,
    direction: Literal["above", "below"] = "above",
    bands: SeverityBands | None = None,
) -> dict[str, int | str | float]:
    """Fields to merge into an anomalies document."""
    level, severity_type = compute_severity(observed, limit, direction, bands)
    ratio = breach_ratio(observed, limit, direction)
    return {
        "severity_level": level,
        "severity_type": severity_type,
        "breach_ratio": round(ratio, 4),
    }
