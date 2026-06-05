"""Unit tests for read routes filters and response contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from ingestor_service import routes_read

from tests.fakes import FakeDB


@pytest.fixture
def fake_db(monkeypatch):
    now = datetime.now(timezone.utc)
    db = FakeDB()
    db.add_collection(
        "anomalies",
        [
            {"_id": "m1", "anomaly_id": "ANOM-1", "status": "unresolved", "sensor_id": "SENS-1", "timestamp_utc": now},
            {
                "_id": "m2",
                "anomaly_id": "ANOM-2",
                "status": "analyzed",
                "sensor_id": "SENS-2",
                "timestamp_utc": now - timedelta(minutes=1),
            },
        ],
    )
    db.add_collection(
        "sensors",
        [
            {
                "_id": "s1",
                "sensor_id": "SENS-1",
                "equipment_type": "centrifugal_pump",
                "metric_type": "vibration",
            }
        ],
    )
    db.add_collection(
        "telemetry_history",
        [
            {"_id": "t1", "sensor_id": "SENS-1", "timestamp_utc": now - timedelta(minutes=30), "reading": {"x": 1}},
            {"_id": "t2", "sensor_id": "SENS-1", "timestamp_utc": now - timedelta(minutes=5), "reading": {"x": 2}},
            {"_id": "t3", "sensor_id": "SENS-2", "timestamp_utc": now - timedelta(minutes=5), "reading": {"x": 3}},
        ],
    )
    db.add_collection(
        "staff_on_call",
        [
            {
                "_id": "e1",
                "employee_id": "EMP-1",
                "is_active": True,
                "is_on_call": True,
                "specialization": ["vibration"],
                "handled_severity_type": "high",
                "facility_ids": ["FAC-1"],
                "escalation_rank": 1,
            },
            {
                "_id": "e2",
                "employee_id": "EMP-2",
                "is_active": True,
                "is_on_call": True,
                "specialization": ["environment"],
                "handled_severity_type": "low",
                "facility_ids": ["FAC-2"],
                "escalation_rank": 2,
            },
        ],
    )
    monkeypatch.setattr(routes_read, "col", db)
    return db


def test_get_anomaly_strips_mongo_id(fake_db):
    out = routes_read.get_anomaly("ANOM-1")
    assert out["anomaly_id"] == "ANOM-1"
    assert "_id" not in out


def test_get_anomaly_404_when_missing(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_read.get_anomaly("ANOM-missing")
    assert err.value.status_code == 404


def test_list_anomalies_filters_by_status_and_sensor(fake_db):
    out = routes_read.list_anomalies(status="unresolved", sensor_id="SENS-1", limit=10)
    assert len(out) == 1
    assert out[0]["anomaly_id"] == "ANOM-1"


def test_recent_readings_filters_by_sensor_and_time_window(fake_db):
    out = routes_read.recent_readings("SENS-1", minutes=10, limit=10)
    assert len(out) == 1
    assert out[0]["reading"] == {"x": 2}
    assert "_id" not in out[0]


def test_knowledge_search_parses_error_codes_csv(monkeypatch, fake_db):
    called = {}

    def _fake_search(query, *, equipment_type=None, error_codes=None, k=5):
        called["query"] = query
        called["equipment_type"] = equipment_type
        called["error_codes"] = error_codes
        called["k"] = k
        return [{"document_id": "kb-1"}]

    monkeypatch.setattr(routes_read, "search_knowledge", _fake_search)
    out = routes_read.knowledge_search(
        q="pump vibration issue",
        equipment_type="centrifugal_pump",
        error_codes="VIBRATION_HIGH, BEARING_WEAR",
        k=3,
    )
    assert out == [{"document_id": "kb-1"}]
    assert called["query"] == "pump vibration issue"
    assert called["equipment_type"] == "centrifugal_pump"
    assert called["error_codes"] == ["VIBRATION_HIGH", "BEARING_WEAR"]
    assert called["k"] == 3


def test_list_on_call_applies_filters(fake_db):
    out = routes_read.list_on_call(
        is_on_call=True,
        specialization="vibration",
        handled_severity_type="high",
        facility_id="FAC-1",
    )
    assert len(out) == 1
    assert out[0]["employee_id"] == "EMP-1"
    assert "_id" not in out[0]
