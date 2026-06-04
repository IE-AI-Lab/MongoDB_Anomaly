"""Unit tests for the threshold lookup mapping.

We monkeypatch `_load_global_threshold` so no MongoDB connection is needed —
the logic under test is the metric -> (direction, limit, consecutive) mapping.
"""

from __future__ import annotations

from ingestor_service.detector import thresholds


def _patch(monkeypatch, rules):
    monkeypatch.setattr(
        thresholds,
        "_load_global_threshold",
        lambda metric_name: {"rules": rules} if rules is not None else None,
    )


def test_temp_is_above(monkeypatch):
    _patch(monkeypatch, {"max_allowed_temp_celsius": 80.0, "consecutive_violating_pings_required": 2})
    t = thresholds.get_threshold("SENS-X", "temp_celsius")
    assert t is not None
    assert (t.direction, t.limit, t.consecutive_required) == ("above", 80.0, 2)


def test_amplitude_is_above_default_consecutive(monkeypatch):
    # No consecutive key -> defaults to 3.
    _patch(monkeypatch, {"max_allowed_amplitude_mm": 0.5})
    t = thresholds.get_threshold("SENS-X", "amplitude_mm")
    assert (t.direction, t.limit, t.consecutive_required) == ("above", 0.5, 3)


def test_pressure_is_below(monkeypatch):
    _patch(monkeypatch, {"min_allowed_pressure_bar": 4.5, "consecutive_violating_pings_required": 2})
    t = thresholds.get_threshold("SENS-X", "pressure_bar")
    assert (t.direction, t.limit) == ("below", 4.5)


def test_flow_is_below(monkeypatch):
    _patch(monkeypatch, {"min_allowed_flow_rate_lpm": 12.0, "consecutive_violating_pings_required": 2})
    t = thresholds.get_threshold("SENS-X", "flow_rate_lpm")
    assert (t.direction, t.limit) == ("below", 12.0)


def test_no_config_returns_none(monkeypatch):
    _patch(monkeypatch, None)
    assert thresholds.get_threshold("SENS-X", "temp_celsius") is None


def test_unknown_metric_returns_none(monkeypatch):
    _patch(monkeypatch, {"some_rule": 1})
    assert thresholds.get_threshold("SENS-X", "not_a_real_metric") is None
