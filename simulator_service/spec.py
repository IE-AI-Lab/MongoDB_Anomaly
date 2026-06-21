"""
Simulator fleet specification.

This module defines:
- How many sensors exist
- Which metric_type each sensor produces
- Context fields (facility/equipment)

In v1 we keep this as a plain Python list so it's easy to edit during development.
Later, you can move this into a YAML/JSON file or a `sensors` seed script.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MetricType = Literal["environment", "vibration", "pressure", "flow"]


@dataclass(frozen=True)
class SensorSpec:
    """Static metadata for a single sensor stream.

    The fleet models the monitoring points of ONE ball mill (MILL-01). The
    `equipment_id` / metric_type here mirror the `sensors` seed in
    scripts/init_db.py. `default_stress` is only a fallback degradation rate used
    until the live per-sensor `sim_stress` (the dashboard slider) is fetched from
    the API; the seeded sensor doc is the source of truth at runtime.
    """

    sensor_id: str
    metric_type: MetricType
    facility_id: str
    equipment_id: str
    default_stress: float = 0.2


SENSORS: list[SensorSpec] = [
    SensorSpec("SENS-ENV-001", "environment", "FAC-01", "MILL-01-TRUNNION-DE", 0.25),
    SensorSpec("SENS-ENV-002", "environment", "FAC-01", "MILL-01-TRUNNION-NDE", 0.15),
    SensorSpec("SENS-VIB-001", "vibration", "FAC-01", "MILL-01-GIRTH-GEAR", 0.30),
    SensorSpec("SENS-VIB-002", "vibration", "FAC-01", "MILL-01-PINION", 0.20),
    SensorSpec("SENS-PRES-001", "pressure", "FAC-01", "MILL-01-LUBE-OIL", 0.15),
    SensorSpec("SENS-FLOW-001", "flow", "FAC-01", "MILL-01-COOLANT", 0.15),
]

