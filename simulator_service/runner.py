"""
Simulator runner.

This is the orchestration layer:
- iterate sensors
- generate a reading per sensor
- build the standardized telemetry event envelope
- send it to the ingestor over HTTP
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .generators import (
    FaultMode,
    generate_environment,
    generate_flow,
    generate_pressure,
    generate_vibration,
    pick_fault,
)
from .http_client import post_telemetry
from .spec import SensorSpec, SENSORS


@dataclass
class SensorRuntimeState:
    """Mutable per-sensor runtime state (sequence counters, last values, etc.)."""

    sequence_number: int = 0


def utc_now_iso() -> str:
    """Return an ISO8601 UTC timestamp string with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_event(
    sensor: SensorSpec,
    state: SensorRuntimeState,
    forced_fault: FaultMode | None = None,
    prob_low: float = 0.08,
    prob_med: float = 0.04,
    prob_high: float = 0.02,
) -> dict[str, Any]:
    """
    Build one telemetry event for a sensor.

    The payload matches the ingestor's TelemetryIngestEvent contract.
    """
    fault = forced_fault if forced_fault is not None else pick_fault(prob_low, prob_med, prob_high)
    if sensor.metric_type == "environment":
        data, quality = generate_environment(fault)
    elif sensor.metric_type == "vibration":
        data, quality = generate_vibration(fault)
    elif sensor.metric_type == "pressure":
        data, quality = generate_pressure(fault)
    else:
        data, quality = generate_flow(fault)

    state.sequence_number += 1

    return {
        "event_id": str(uuid4()),
        "timestamp_utc": utc_now_iso(),
        "sensor_id": sensor.sensor_id,
        "facility_id": sensor.facility_id,
        "equipment_id": sensor.equipment_id,
        "source": "simulator",
        "quality": quality,
        "sequence_number": state.sequence_number,
        "reading": {
            "metric_type": sensor.metric_type,
            "unit_system": "si",
            "data": data,
        },
    }


def run(
    base_url: str,
    tick_seconds: int = 5,
    emit_probability: float = 0.7,
    prob_low: float = 0.08,
    prob_med: float = 0.04,
    prob_high: float = 0.02,
    deterministic_demo: bool = False,
    demo_interval_ticks: int = 10,
) -> None:
    """
    Start the simulator loop.

    Behavior:
    - Each tick, sensors are considered in a RANDOM order (shuffled).
    - Each sensor independently emits with probability `emit_probability`,
      so the number of events per tick varies instead of always being all sensors.
    - Sleeps between ticks to approximate real-time.
    - Prints a minimal progress line every tick.
    - If deterministic_demo is enabled, every `demo_interval_ticks` we force at least
      one guaranteed anomaly by emitting two high-fault readings for SENS-ENV-001.

    Why randomized:
    - Real fleets do not report in a fixed, synchronized order every interval.
    - Consecutive-violation detection still works; it just spans more ticks for
      sensors that occasionally skip a tick.
    """
    states: dict[str, SensorRuntimeState] = {s.sensor_id: SensorRuntimeState() for s in SENSORS}

    tick = 0
    while True:
        tick += 1

        shuffled = list(SENSORS)
        random.shuffle(shuffled)

        sent = 0
        for sensor in shuffled:
            if random.random() > emit_probability:
                continue
            payload = build_event(
                sensor,
                states[sensor.sensor_id],
                prob_low=prob_low,
                prob_med=prob_med,
                prob_high=prob_high,
            )
            post_telemetry(base_url, payload)
            sent += 1

        if deterministic_demo and demo_interval_ticks > 0 and tick % demo_interval_ticks == 0:
            demo_sensor = next((s for s in SENSORS if s.sensor_id == "SENS-ENV-001"), SENSORS[0])
            # consecutive requirement is 2, so two forced high readings guarantees a trigger.
            payload_1 = build_event(demo_sensor, states[demo_sensor.sensor_id], forced_fault="high")
            payload_2 = build_event(demo_sensor, states[demo_sensor.sensor_id], forced_fault="high")
            post_telemetry(base_url, payload_1)
            post_telemetry(base_url, payload_2)
            sent += 2
            print(
                f"[SIM] demo injected guaranteed anomaly on tick={tick} "
                f"sensor={demo_sensor.sensor_id}"
            )

        print(f"[SIM] tick={tick} sent={sent}/{len(SENSORS)} events")
        time.sleep(tick_seconds)

