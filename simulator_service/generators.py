"""
Telemetry generators — a ball-mill signal model.

Each sensor stream carries a *continuous* signal rather than independent random
draws, so the dashboard shows realistic, autocorrelated telemetry that trends,
oscillates, and occasionally spikes — like a real ball mill being monitored.

The value of the primary (alarm-bearing) metric each tick is:

    value = baseline
          + seasonal      # slow sine — mill load / thermal cycle
          + ar1_noise      # smooth, autocorrelated measurement noise
          + sign * (wear + sub_threshold_spike)

where `sign` is +1 for "above" alarms (temperature, vibration) and -1 for
"below" alarms (lube pressure, coolant flow), so degradation always pushes the
value toward its limit.

Three anomaly-shaping behaviours, all driven by the per-machine `stress` slider
(0 = healthy/flat, 1 = steep climb) and the run-mode the runner assigns:

- **Gradual degradation**: in NORMAL mode `wear` accumulates each tick at a rate
  set by `stress`. With noise the exact crossing tick is random, but the
  steepness/frequency is the slider — bearing wear, liner wear, scaling.
- **Sudden step-fault**: an occasional instantaneous jump of `wear` clear over
  the limit (e.g. a lube-pump trip), injected by the runner via `inject_step`.
- **Sub-threshold texture**: frequent small spikes that stay *under* the limit on
  a healthy machine (ball impacts, cataracting charge) — realism, not anomalies.

Once the value crosses the limit the detector fires and the runner switches the
sensor to HOLD (breach is sustained), then to RECOVER once a worker resolves the
anomaly (`wear` decays back to baseline). The signal only decreases after the
worker says it's done.

Realistic baselines/limits (mirror the seeded thresholds in scripts/init_db.py):
- trunnion bearing temp ~50 C, alarm 70 C
- drivetrain vibration ~2.5 mm/s RMS, alarm 7.1 mm/s (ISO 10816)
- lube-oil pressure ~6.5 bar, min 4.5 bar
- coolant flow ~18 L/min, min 12 L/min
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Literal

Quality = Literal["good", "suspect", "bad"]
Mode = Literal["normal", "hold", "recover"]


@dataclass
class MetricProfile:
    """Signal parameters for a metric_type's primary (alarm-bearing) metric."""

    field: str
    direction: Literal["above", "below"]
    baseline: float
    limit: float
    season_amp: float
    season_period_s: float
    noise_sigma: float
    noise_rho: float          # AR(1) coefficient; high = slow/smooth (thermal inertia)
    spike_prob: float         # per-tick chance of a sub-threshold texture spike
    decimals: int
    floor: float = 0.0        # physical lower clamp (values can't go negative)

    @property
    def margin(self) -> float:
        """Distance from baseline to the alarm limit (always positive)."""
        return abs(self.limit - self.baseline)

    @property
    def sign(self) -> int:
        """+1 if breaching means going up, -1 if breaching means going down."""
        return 1 if self.direction == "above" else -1


# Keyed by metric_type. Only the primary metric degrades; secondary metrics
# (humidity, frequency) are benign context generated in `_secondary`.
PROFILES: dict[str, MetricProfile] = {
    "environment": MetricProfile(
        field="temp_celsius", direction="above", baseline=50.0, limit=70.0,
        season_amp=2.0, season_period_s=200.0,
        noise_sigma=0.35, noise_rho=0.92, spike_prob=0.04, decimals=2,
    ),
    "vibration": MetricProfile(
        field="amplitude_mm", direction="above", baseline=2.5, limit=7.1,
        season_amp=0.45, season_period_s=120.0,
        noise_sigma=0.18, noise_rho=0.55, spike_prob=0.15, decimals=3,
    ),
    "pressure": MetricProfile(
        field="pressure_bar", direction="below", baseline=6.5, limit=4.5,
        season_amp=0.22, season_period_s=160.0,
        noise_sigma=0.10, noise_rho=0.70, spike_prob=0.05, decimals=2,
    ),
    "flow": MetricProfile(
        field="flow_rate_lpm", direction="below", baseline=18.0, limit=12.0,
        season_amp=1.1, season_period_s=150.0,
        noise_sigma=0.45, noise_rho=0.70, spike_prob=0.05, decimals=2,
    ),
}

# Tuning knobs (per tick).
_WEAR_FRACTION = 0.06     # at stress=1, wear gains ~6% of margin/tick → crosses in ~17 ticks
_HOLD_OVERSHOOT = (1.10, 1.45)   # wear (× margin) held during an active anomaly
_STEP_OVERSHOOT = (1.05, 1.40)   # wear (× margin) on a sudden step-fault
_RECOVER_DECAY = 0.55     # wear multiplier each tick while recovering
_RECOVERED_FRACTION = 0.05  # wear <= margin * this → fully recovered
_SPIKE_RANGE = (0.20, 0.60)  # texture spike size as a fraction of margin


@dataclass
class SignalState:
    """Mutable per-sensor signal state (carried across ticks by the runner)."""

    wear: float = 0.0
    noise: float = 0.0
    phase: float = 0.0   # per-sensor seasonal offset so machines aren't in lockstep

    @classmethod
    def new(cls, period_s: float) -> "SignalState":
        return cls(phase=random.uniform(0.0, period_s))


def recovered(metric_type: str, st: SignalState) -> bool:
    """True once a recovering signal has decayed back to its baseline."""
    return st.wear <= PROFILES[metric_type].margin * _RECOVERED_FRACTION


def _primary_value(
    profile: MetricProfile,
    st: SignalState,
    *,
    stress: float,
    mode: Mode,
    t_seconds: float,
    inject_step: bool,
) -> float:
    """Advance the primary metric one tick and return its value (mutates `st`)."""
    margin = profile.margin

    # AR(1) noise: smooth, autocorrelated wandering instead of white jitter.
    st.noise = profile.noise_rho * st.noise + random.gauss(0.0, profile.noise_sigma)
    season = profile.season_amp * math.sin(2 * math.pi * (t_seconds + st.phase) / profile.season_period_s)

    spike = 0.0
    if mode == "normal":
        # Gradual degradation, steepness set by the slider.
        st.wear += _WEAR_FRACTION * max(0.0, stress) * margin * random.uniform(0.6, 1.4)
        if inject_step:
            st.wear = max(st.wear, margin * random.uniform(*_STEP_OVERSHOOT))
        # Sub-threshold texture: small, kept under the limit on a healthy machine.
        if random.random() < profile.spike_prob:
            spike = random.uniform(*_SPIKE_RANGE) * margin
    elif mode == "hold":
        # Keep the breach clearly past the limit until a worker resolves it.
        st.wear = max(st.wear, margin * random.uniform(*_HOLD_OVERSHOOT))
    else:  # recover
        st.wear *= _RECOVER_DECAY

    value = profile.baseline + season + st.noise + profile.sign * (st.wear + spike)
    return max(profile.floor, round(value, profile.decimals))


def _secondary(metric_type: str) -> dict[str, Any]:
    """Benign secondary readings (not alarm-bearing) for richer context."""
    if metric_type == "environment":
        return {"humidity_percent": round(45.0 + random.gauss(0.0, 3.0), 2)}
    if metric_type == "vibration":
        # Dominant vibration frequency (gear-mesh / running speed band), stable.
        return {"frequency_hz": round(50.0 + random.gauss(0.0, 1.5), 2)}
    return {}


def generate_reading(
    metric_type: str,
    st: SignalState,
    *,
    stress: float,
    mode: Mode,
    t_seconds: float,
    inject_step: bool = False,
) -> tuple[dict[str, Any], Quality]:
    """
    Produce one reading's `data` dict (all metric fields) + quality.

    `st` carries the signal across ticks and is mutated in place. `mode` is the
    fault-state-machine mode the runner assigns (normal / hold / recover).
    """
    profile = PROFILES[metric_type]
    value = _primary_value(
        profile, st, stress=stress, mode=mode, t_seconds=t_seconds, inject_step=inject_step
    )
    data: dict[str, Any] = {profile.field: value, **_secondary(metric_type)}
    return data, "good"
