"""Unit tests for the detector pipeline.

Pure helpers (`_extract_metric_candidates`, `_is_violation`, `_error_code`) are
tested directly. `process_telemetry` is tested with DB writes, the agent stub,
and threshold lookup monkeypatched out, so we exercise the consecutive-violation
gating and the anomaly document shape without a live MongoDB.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestor_service.detector import detect, state
from ingestor_service.detector.thresholds import Threshold


# --- pure helpers ----------------------------------------------------------

def test_extract_environment_candidates():
    doc = {"reading": {"metric_type": "environment", "temp_celsius": 90.0, "humidity_percent": 40}}
    pairs = detect._extract_metric_candidates(doc)
    assert ("temp_celsius", 90.0) in pairs
    assert ("humidity_percent", 40.0) in pairs


def test_extract_ignores_non_numeric_and_other_types():
    doc = {"reading": {"metric_type": "vibration", "amplitude_mm": "oops"}}
    assert detect._extract_metric_candidates(doc) == []


def test_is_violation_above_and_below():
    above = Threshold("amplitude_mm", "above", 0.5, 2)
    assert detect._is_violation(0.7, above) is True
    assert detect._is_violation(0.4, above) is False

    below = Threshold("pressure_bar", "below", 4.5, 2)
    assert detect._is_violation(3.0, below) is True
    assert detect._is_violation(5.0, below) is False


def test_error_code_mapping():
    above = Threshold("temp_celsius", "above", 80.0, 2)
    below = Threshold("temp_celsius", "below", 10.0, 2)
    assert detect._error_code("temp_celsius", above) == "TEMP_HIGH"
    assert detect._error_code("temp_celsius", below) == "TEMP_LOW"
    assert detect._error_code("amplitude_mm", above) == "VIBRATION_HIGH"
    assert detect._error_code("pressure_bar", below) == "PRESSURE_LOW"
    assert detect._error_code("flow_rate_lpm", below) == "FLOW_LOW"


# --- process_telemetry -----------------------------------------------------

class _FakeCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(doc)


class _FakeDB:
    def __init__(self):
        self.cols: dict[str, _FakeCollection] = {}

    def __call__(self, name):
        return self.cols.setdefault(name, _FakeCollection())


@pytest.fixture
def fake_col(monkeypatch):
    state.reset_all()
    fake = _FakeDB()
    monkeypatch.setattr(detect, "col", fake)
    monkeypatch.setattr(detect, "dispatch_anomaly", lambda doc: None)
    return fake


def _telemetry(value):
    return {
        "sensor_id": "SENS-VIB-001",
        "timestamp_utc": datetime.now(timezone.utc),
        "facility_id": "FAC-01",
        "equipment_id": "PUMP-A12",
        "reading": {"metric_type": "vibration", "amplitude_mm": value},
    }


def test_anomaly_triggers_only_after_consecutive_required(monkeypatch, fake_col):
    threshold = Threshold("amplitude_mm", "above", 0.5, 2)
    monkeypatch.setattr(detect, "get_threshold", lambda sensor_id, metric_name: threshold)

    # First violating reading: counter = 1, below required 2 -> no anomaly.
    assert detect.process_telemetry(_telemetry(0.7)) is None
    # Second consecutive violation: triggers.
    anomaly = detect.process_telemetry(_telemetry(0.7))
    assert anomaly is not None

    assert anomaly["status"] == "unresolved"
    assert anomaly["error_code"] == "VIBRATION_HIGH"
    assert anomaly["metric_type"] == "vibration"
    assert anomaly["severity_type"] == "high"  # 0.7 vs 0.5 -> ratio 0.4
    assert anomaly["trigger_value"]["consecutive_count"] == 2
    assert anomaly["anomaly_id"].startswith("ANOM-")

    # Persisted to anomalies + emitted a session event.
    assert len(fake_col("anomalies").docs) == 1
    assert len(fake_col("session_events").docs) == 1


def test_normal_reading_resets_counter(monkeypatch, fake_col):
    threshold = Threshold("amplitude_mm", "above", 0.5, 2)
    monkeypatch.setattr(detect, "get_threshold", lambda sensor_id, metric_name: threshold)

    assert detect.process_telemetry(_telemetry(0.7)) is None  # counter -> 1
    assert detect.process_telemetry(_telemetry(0.1)) is None  # normal -> reset to 0
    assert detect.process_telemetry(_telemetry(0.7)) is None  # counter -> 1 again, no trigger
    assert fake_col("anomalies").docs == []


def test_no_threshold_means_no_anomaly(monkeypatch, fake_col):
    monkeypatch.setattr(detect, "get_threshold", lambda sensor_id, metric_name: None)
    assert detect.process_telemetry(_telemetry(99.0)) is None
    assert fake_col("anomalies").docs == []
