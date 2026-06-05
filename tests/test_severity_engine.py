"""Unit tests for severity_engine — pure functions, no DB."""

from __future__ import annotations

import pytest

from ingestor_service.severity_engine import (
    breach_ratio,
    build_anomaly_severity_fields,
    compute_severity,
)


# --- breach_ratio ----------------------------------------------------------

def test_breach_ratio_above_within_limit_is_zero():
    assert breach_ratio(80.0, 80.0, "above") == 0.0
    assert breach_ratio(50.0, 80.0, "above") == 0.0


def test_breach_ratio_above():
    # 100 vs max 80 -> 20/80 = 0.25 (the README's canonical example)
    assert breach_ratio(100.0, 80.0, "above") == pytest.approx(0.25)


def test_breach_ratio_below_within_limit_is_zero():
    assert breach_ratio(4.5, 4.5, "below") == 0.0
    assert breach_ratio(6.0, 4.5, "below") == 0.0


def test_breach_ratio_below():
    # 2.5 vs min 4.5 -> 2.0/4.5
    assert breach_ratio(2.5, 4.5, "below") == pytest.approx(2.0 / 4.5)


def test_breach_ratio_zero_limit_raises():
    with pytest.raises(ValueError):
        breach_ratio(10.0, 0.0, "above")


# --- compute_severity ------------------------------------------------------

def test_severity_no_breach_is_low_level_1():
    assert compute_severity(80.0, 80.0, "above") == (1, "low")


def test_severity_low_band():
    # ratio 0.05 (< 0.10) -> low; midpoint of 1..3 band
    level, sev = compute_severity(84.0, 80.0, "above")
    assert sev == "low"
    assert 1 <= level <= 3


def test_severity_medium_band_lower_edge():
    # ratio exactly 0.10 -> medium, bottom of the 4..7 band
    assert compute_severity(88.0, 80.0, "above") == (4, "medium")


def test_severity_high_band_is_level_10():
    # ratio 0.25 -> high; engine pins high to level 10
    assert compute_severity(100.0, 80.0, "above") == (10, "high")
    assert compute_severity(120.0, 80.0, "above") == (10, "high")


def test_severity_below_direction_high():
    level, sev = compute_severity(2.5, 4.5, "below")
    assert sev == "high"
    assert level == 10


# --- build_anomaly_severity_fields -----------------------------------------

def test_build_fields_shape():
    fields = build_anomaly_severity_fields(100.0, 80.0, "above")
    assert fields == {
        "severity_level": 10,
        "severity_type": "high",
        "breach_ratio": 0.25,
    }
