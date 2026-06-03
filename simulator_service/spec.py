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
    """Static metadata for a single sensor stream."""

    sensor_id: str
    metric_type: MetricType
    facility_id: str
    equipment_id: str


SENSORS: list[SensorSpec] = [
    SensorSpec("SENS-ENV-001", "environment", "FAC-01", "ROOM-PACK-01"),
    SensorSpec("SENS-ENV-002", "environment", "FAC-01", "ROOM-CTRL-01"),
    SensorSpec("SENS-VIB-001", "vibration", "FAC-01", "PUMP-A12"),
    SensorSpec("SENS-VIB-002", "vibration", "FAC-01", "MOTOR-B07"),
    SensorSpec("SENS-PRES-001", "pressure", "FAC-01", "HYD-LINE-03"),
    SensorSpec("SENS-FLOW-001", "flow", "FAC-01", "COOL-LOOP-01"),
]

