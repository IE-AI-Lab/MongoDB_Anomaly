"""Unit tests for POST /simulation/reset."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestor_service import routes_admin

from tests.fakes import FakeDB


NOW = datetime.now(timezone.utc)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    db.add_collection("anomalies", [{"anomaly_id": "ANOM-1"}, {"anomaly_id": "ANOM-2"}])
    db.add_collection("telemetry_history", [{"sensor_id": "SENS-1"}])
    db.add_collection("agent_execution_logs", [{"run_id": "run-1"}])
    db.add_collection("session_events", [])
    db.add_collection(
        "staff_on_call",
        [
            {"employee_id": "EMP-001", "is_on_call": False},
            {"employee_id": "EMP-002", "is_on_call": True},
        ],
    )
    db.add_collection(
        "knowledge_base",
        [
            {"document_id": "seed-000", "is_active": True},
            {"document_id": "fb-1234", "is_active": False},
        ],
    )
    monkeypatch.setattr(routes_admin, "col", db)
    # Keep the unit test off Redis regardless of local .env.
    monkeypatch.setattr(routes_admin.queue, "trim_anomaly_stream", lambda: False)
    return db


def test_reset_purges_runtime_collections(fake_db):
    result = routes_admin.reset_simulation(routes_admin.ResetRequest())
    assert result["deleted"]["anomalies"] == 2
    assert result["deleted"]["telemetry_history"] == 1
    assert result["deleted"]["agent_execution_logs"] == 1
    assert result["deleted"]["session_events"] == 0
    assert fake_db("anomalies").docs == []
    assert fake_db("telemetry_history").docs == []


def test_reset_restores_staff_on_call(fake_db):
    result = routes_admin.reset_simulation(routes_admin.ResetRequest())
    assert result["staff_reset"] == 2
    assert all(s["is_on_call"] is True for s in fake_db("staff_on_call").docs)


def test_reset_keeps_feedback_knowledge_by_default(fake_db):
    result = routes_admin.reset_simulation(routes_admin.ResetRequest())
    assert result["deleted"]["knowledge_feedback"] == 0
    assert len(fake_db("knowledge_base").docs) == 2


def test_reset_purges_feedback_knowledge_with_flag(fake_db):
    result = routes_admin.reset_simulation(
        routes_admin.ResetRequest(purge_feedback_knowledge=True)
    )
    assert result["deleted"]["knowledge_feedback"] == 1
    remaining = [d["document_id"] for d in fake_db("knowledge_base").docs]
    assert remaining == ["seed-000"]  # seeds survive


def test_reset_is_idempotent(fake_db):
    routes_admin.reset_simulation(routes_admin.ResetRequest())
    result = routes_admin.reset_simulation(routes_admin.ResetRequest())
    assert all(v == 0 for v in result["deleted"].values())
    assert result["redis_stream_trimmed"] is False
