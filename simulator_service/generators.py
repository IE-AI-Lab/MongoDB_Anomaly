"""
Telemetry generators.

Each generator returns a tuple:
- reading_data: dict of metric fields specific to the sensor type
- quality: "good" | "suspect" | "bad"

Fault injection:
- For demo repeatability, we use a simple "fault mode" per metric type:
  - None: normal operation
  - "low": small threshold breach
  - "medium": medium breach
  - "high": large breach (rare)
"""

from __future__ import annotations

import random
from typing import Any, Literal


FaultMode = Literal["low", "medium", "high"]
Quality = Literal["good", "suspect", "bad"]


def _noise(scale: float) -> float:
    """Uniform noise helper."""
    return random.uniform(-scale, scale)


def generate_environment(fault: FaultMode | None = None) -> tuple[dict[str, Any], Quality]:
    """
    Generate environment readings.

    Normal:
    - temp_celsius around 24 ± 2
    - humidity_percent around 45 ± 8

    Faults:
    - low: temp slightly above threshold
    - medium: clearly above threshold
    - high: large breach (e.g. ~100C to force severity high)
    """
    temp = 24.0 + _noise(2.0)
    humidity = 45.0 + _noise(8.0)

    if fault == "low":
        temp = 82.0 + _noise(0.5)
    elif fault == "medium":
        temp = 88.0 + _noise(1.0)
    elif fault == "high":
        temp = 100.0 + _noise(1.0)

    return {"temp_celsius": round(temp, 2), "humidity_percent": round(humidity, 2)}, "good"


def generate_vibration(fault: FaultMode | None = None) -> tuple[dict[str, Any], Quality]:
    """
    Generate vibration readings.

    Normal amplitude is well below the demo threshold (0.5).
    """
    amplitude = 0.12 + _noise(0.05)
    frequency = 60.0 + _noise(2.0)

    if fault == "low":
        amplitude = 0.55 + _noise(0.02)
    elif fault == "medium":
        amplitude = 0.70 + _noise(0.03)
    elif fault == "high":
        amplitude = 0.95 + _noise(0.05)

    return {"amplitude_mm": round(amplitude, 3), "frequency_hz": round(frequency, 2)}, "good"


def generate_pressure(fault: FaultMode | None = None) -> tuple[dict[str, Any], Quality]:
    """
    Generate pressure readings.

    The detector treats pressure as a "below min" anomaly (pressure drop).
    """
    pressure = 6.5 + _noise(0.4)
    if fault == "low":
        pressure = 4.3 + _noise(0.1)
    elif fault == "medium":
        pressure = 3.6 + _noise(0.1)
    elif fault == "high":
        pressure = 2.5 + _noise(0.2)
    return {"pressure_bar": round(pressure, 2)}, "good"


def generate_flow(fault: FaultMode | None = None) -> tuple[dict[str, Any], Quality]:
    """
    Generate flow readings.

    The detector treats flow as a "below min" anomaly.
    """
    flow = 18.0 + _noise(1.5)
    if fault == "low":
        flow = 11.5 + _noise(0.3)
    elif fault == "medium":
        flow = 9.0 + _noise(0.5)
    elif fault == "high":
        flow = 6.0 + _noise(0.6)
    return {"flow_rate_lpm": round(flow, 2)}, "good"


def pick_fault(prob_low: float = 0.08, prob_med: float = 0.04, prob_high: float = 0.02) -> FaultMode | None:
    """
    Randomly pick a fault mode.

    Keep probabilities low so anomalies are not constant noise.
    """
    r = random.random()
    if r < prob_high:
        return "high"
    if r < prob_high + prob_med:
        return "medium"
    if r < prob_high + prob_med + prob_low:
        return "low"
    return None

