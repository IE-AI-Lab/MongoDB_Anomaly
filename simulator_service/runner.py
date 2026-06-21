"""
Simulator runner.

This is the orchestration layer:
- iterate sensors
- advance each sensor's continuous ball-mill signal (see generators.py)
- run a per-sensor fault state machine so a breach is held until a worker
  resolves it, then decays back to baseline
- build the standardized telemetry event envelope and POST it to the ingestor

Fault state machine (per sensor):

    normal ──(degradation/step crosses the limit → anomaly created)──▶ hold
    hold   ──(worker resolves the anomaly: no longer open)───────────▶ recover
    recover ──(signal decayed back to baseline)─────────────────────▶ normal

The simulator learns which sensors still have an *open* anomaly with one
`GET /anomalies` poll per tick (fail-safe), and reads the per-sensor `sim_stress`
slider with a periodic `GET /sensors` poll (fail-open to cached/default).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .generators import Mode, SignalState, generate_reading, recovered, PROFILES
from .http_client import (
    get_open_anomaly_sensors,
    get_sensor_stress,
    get_simulation_status,
    post_telemetry,
)
from .spec import SensorSpec, SENSORS

# How often to refresh the per-sensor stress slider values from the API.
_STRESS_REFRESH_TICKS = 6
# Per-tick probability of a sudden step-fault, at stress=1 (scales with stress).
_STEP_PROB_AT_MAX = 0.006
# With --deterministic-demo, clamp every sensor's effective stress to at least
# this, so a fresh demo produces anomalies promptly out of the box.
_DEMO_STRESS_FLOOR = 0.5


@dataclass
class SensorRuntimeState:
    """Mutable per-sensor runtime state across ticks."""

    signal: SignalState
    sequence_number: int = 0
    mode: Mode = "normal"
    # Set once the detector has actually created an anomaly for the current
    # breach, so we don't recover during the warm-up before it fires.
    anomaly_observed: bool = False


def utc_now_iso() -> str:
    """Return an ISO8601 UTC timestamp string with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_event(
    sensor: SensorSpec,
    state: SensorRuntimeState,
    *,
    stress: float,
    t_seconds: float,
    inject_step: bool,
) -> dict[str, Any]:
    """
    Build one telemetry event for a sensor.

    The payload matches the ingestor's TelemetryIngestEvent contract.
    """
    data, quality = generate_reading(
        sensor.metric_type,
        state.signal,
        stress=stress,
        mode=state.mode,
        t_seconds=t_seconds,
        inject_step=inject_step,
    )

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


def _apply_transitions(
    sensor: SensorSpec, state: SensorRuntimeState, open_sensors: set[str]
) -> None:
    """Advance the fault state machine for one sensor based on open anomalies."""
    if sensor.sensor_id in open_sensors:
        # An anomaly exists for this sensor → hold the breach until it's resolved.
        state.anomaly_observed = True
        if state.mode != "hold":
            state.mode = "hold"
    elif state.mode == "hold" and state.anomaly_observed:
        # The anomaly we saw is gone (resolved) → start recovering to baseline.
        state.mode = "recover"


def run(
    base_url: str,
    tick_seconds: int = 5,
    emit_probability: float = 0.7,
    deterministic_demo: bool = False,
) -> None:
    """
    Start the simulator loop.

    Each tick: sensors are considered in random order. A healthy sensor emits
    with probability `emit_probability`; a faulted/recovering sensor emits every
    tick so its breach stays sustained and its recovery is visible. Per-sensor
    `sim_stress` (the dashboard slider) sets how fast each machine degrades.

    `deterministic_demo` raises every sensor's effective stress to a floor so a
    fresh demo trips anomalies promptly without anyone touching the sliders.
    """
    states: dict[str, SensorRuntimeState] = {
        s.sensor_id: SensorRuntimeState(signal=SignalState.new(PROFILES[s.metric_type].season_period_s))
        for s in SENSORS
    }
    stress_map: dict[str, float] = {s.sensor_id: s.default_stress for s in SENSORS}
    open_sensors: set[str] = set()

    tick = 0
    while True:
        tick += 1

        # Run/pause flag, controlled by the UI Start/Stop buttons via the API.
        # Fail-open inside get_simulation_status, so a control-plane error never
        # freezes the loop; we just keep emitting.
        if not get_simulation_status(base_url):
            print(f"[SIM] tick={tick} paused (simulation stopped)")
            time.sleep(tick_seconds)
            continue

        # Refresh slider values periodically (fail-open: keep cache on error).
        if tick == 1 or tick % _STRESS_REFRESH_TICKS == 0:
            latest = get_sensor_stress(base_url)
            if latest:
                stress_map.update(latest)

        # Which sensors still have an open anomaly? Fail-safe: keep last known
        # set on error so a blip doesn't recover every held breach at once.
        latest_open = get_open_anomaly_sensors(base_url)
        if latest_open is not None:
            open_sensors = latest_open

        t_seconds = float(tick * tick_seconds)
        shuffled = list(SENSORS)
        random.shuffle(shuffled)

        sent = 0
        faulted = 0
        for sensor in shuffled:
            state = states[sensor.sensor_id]
            _apply_transitions(sensor, state, open_sensors)

            stress = stress_map.get(sensor.sensor_id, sensor.default_stress)
            if deterministic_demo:
                stress = max(stress, _DEMO_STRESS_FLOOR)

            # Healthy sensors skip some ticks (real fleets aren't synchronized);
            # faulted/recovering sensors always emit so the breach is continuous.
            if state.mode == "normal" and random.random() > emit_probability:
                continue

            inject_step = state.mode == "normal" and random.random() < _STEP_PROB_AT_MAX * stress

            payload = build_event(
                sensor, state, stress=stress, t_seconds=t_seconds, inject_step=inject_step
            )
            post_telemetry(base_url, payload)
            sent += 1

            # Once a recovering signal is back to baseline, return to normal.
            if state.mode == "recover" and recovered(sensor.metric_type, state.signal):
                state.mode = "normal"
                state.anomaly_observed = False
            if state.mode != "normal":
                faulted += 1

        print(f"[SIM] tick={tick} sent={sent}/{len(SENSORS)} events, {faulted} faulted")
        time.sleep(tick_seconds)
