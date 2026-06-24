"""Tests for deterministic manual anomaly creation (the UI "Trigger anomaly"
button): the detect.create_manual_anomaly helper and the POST /simulation/anomaly
route. Dispatch is monkeypatched out — no Redis/agent needed."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from ingestor_service.api import admin as routes_admin
from ingestor_service.detector import detect, state
from ingestor_service.detector import thresholds as thresholds_mod

from tests.fakes import FakeDB


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    db.add_collection(
        "sensors",
        [
            {
                "_id": "s1",
                "sensor_id": "MILL-01-BRG",
                "equipment_id": "MILL-01",
                "facility_id": "FAC-1",
                "metric_type": "environment",
                "is_active": True,
            }
        ],
    )
    db.add_collection(
        "system_metadata",
        [
            {
                "_id": "c1",
                "config_type": "anomaly_thresholds",
                "target_metric": "temp_celsius",
                "is_enabled": True,
                "rules": {
                    "max_allowed_temp_celsius": 70.0,
                    "consecutive_violating_pings_required": 1,
                },
            }
        ],
    )
    db.add_collection("anomalies", [])
    db.add_collection("telemetry_history", [])
    db.add_collection("session_events", [])
    # detect.col + the threshold module's col both resolve to the same fake.
    monkeypatch.setattr(detect, "col", db)
    monkeypatch.setattr(thresholds_mod, "col", db)
    state.reset_all()  # in-process detector counters
    return db


def test_create_manual_anomaly_with_threshold(fake_db, monkeypatch):
    dispatched: list = []
    monkeypatch.setattr(detect, "dispatch_anomaly", lambda d: dispatched.append(d))

    sensor = fake_db("sensors").find_one({"sensor_id": "MILL-01-BRG"})
    anomaly = detect.create_manual_anomaly(sensor)

    # Shaped like a real threshold breach.
    assert anomaly["error_code"] == "TEMP_HIGH"
    assert anomaly["detection_method"] == "threshold"
    assert anomaly["status"] == "unresolved"
    # 70 * 1.25 = 87.5 → breach ratio 0.25 → high severity.
    assert anomaly["trigger_value"]["observed"] == 87.5
    assert anomaly["trigger_value"]["limit"] == 70.0
    assert anomaly["severity_type"] == "high"

    # Persisted to both collections, and dispatched exactly once.
    assert len(list(fake_db("anomalies").find({}))) == 1
    assert len(list(fake_db("telemetry_history").find({}))) == 1
    assert [d["anomaly_id"] for d in dispatched] == [anomaly["anomaly_id"]]

    # Counter disarmed so the held breach won't produce a second, detector anomaly.
    counter = state.get_counter("MILL-01-BRG", "temp_celsius")
    assert counter.threshold_armed is False


def test_create_manual_anomaly_falls_back_without_threshold(fake_db, monkeypatch):
    monkeypatch.setattr(detect, "dispatch_anomaly", lambda d: None)

    # No amplitude_mm threshold seeded → fallback (7.1, "above").
    sensor = {
        "sensor_id": "MILL-01-VIB",
        "equipment_id": "MILL-01",
        "facility_id": "FAC-1",
        "metric_type": "vibration",
        "is_active": True,
    }
    anomaly = detect.create_manual_anomaly(sensor)

    assert anomaly["error_code"] == "VIBRATION_HIGH"
    assert anomaly["trigger_value"]["limit"] == 7.1
    assert anomaly["trigger_value"]["observed"] == 8.875  # 7.1 * 1.25
    assert anomaly["severity_type"] == "high"


def test_endpoint_returns_summary_fields(monkeypatch):
    db = FakeDB()
    db.add_collection(
        "sensors",
        [{"_id": "s1", "sensor_id": "MILL-01-BRG", "is_active": True, "metric_type": "environment"}],
    )
    monkeypatch.setattr(routes_admin, "col", db)
    monkeypatch.setattr(
        routes_admin.detect,
        "create_manual_anomaly",
        lambda sensor: {
            "anomaly_id": "ANOM-x",
            "sensor_id": sensor["sensor_id"],
            "error_code": "TEMP_HIGH",
            "severity_type": "high",
            "severity_level": 10,
            "status": "unresolved",
        },
    )

    resp = routes_admin.create_anomaly(routes_admin.CreateAnomalyRequest(sensor_id="MILL-01-BRG"))
    assert resp["anomaly_id"] == "ANOM-x"
    assert resp["sensor_id"] == "MILL-01-BRG"
    assert resp["severity_type"] == "high"
    assert resp["status"] == "unresolved"


def test_endpoint_defaults_to_first_active_sensor(monkeypatch):
    db = FakeDB()
    db.add_collection(
        "sensors",
        [{"_id": "s1", "sensor_id": "MILL-01-BRG", "is_active": True, "metric_type": "environment"}],
    )
    monkeypatch.setattr(routes_admin, "col", db)
    seen: dict = {}
    monkeypatch.setattr(
        routes_admin.detect,
        "create_manual_anomaly",
        lambda sensor: seen.update(sensor) or {
            "anomaly_id": "ANOM-y", "sensor_id": sensor["sensor_id"], "error_code": "TEMP_HIGH",
            "severity_type": "high", "severity_level": 10, "status": "unresolved",
        },
    )

    resp = routes_admin.create_anomaly(routes_admin.CreateAnomalyRequest())  # no sensor_id
    assert resp["sensor_id"] == "MILL-01-BRG"
    assert seen["sensor_id"] == "MILL-01-BRG"  # picked the active sensor


def test_endpoint_404_when_sensor_missing(monkeypatch):
    db = FakeDB()
    db.add_collection("sensors", [])
    monkeypatch.setattr(routes_admin, "col", db)

    with pytest.raises(HTTPException) as err:
        routes_admin.create_anomaly(routes_admin.CreateAnomalyRequest(sensor_id="NOPE"))
    assert err.value.status_code == 404
