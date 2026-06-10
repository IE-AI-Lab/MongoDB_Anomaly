"""Unit tests for the agent_execution_logs write/read endpoints."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from ingestor_service import routes_agent_logs

from tests.fakes import FakeDB


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    db.add_collection("agent_execution_logs", [])
    monkeypatch.setattr(routes_agent_logs, "col", db)
    return db


def test_post_creates_running_log_with_started_at(fake_db):
    result = routes_agent_logs.upsert_agent_log(
        routes_agent_logs.AgentLogUpsert(
            run_id="run-1",
            anomaly_id="ANOM-1",
            status="running",
            agent_name="mongodb-anomaly-agent",
        )
    )
    assert result["run_id"] == "run-1"
    assert result["status"] == "running"
    assert result["started_at"] is not None
    assert "_id" not in result


def test_post_is_upsert_keyed_by_run_id(fake_db):
    routes_agent_logs.upsert_agent_log(
        routes_agent_logs.AgentLogUpsert(run_id="run-1", anomaly_id="ANOM-1", status="running")
    )
    completed = routes_agent_logs.upsert_agent_log(
        routes_agent_logs.AgentLogUpsert(
            run_id="run-1",
            anomaly_id="ANOM-1",
            status="completed",
            final_action_taken="analyzed",
        )
    )

    # One document, updated in place — not a second insert.
    assert len(fake_db("agent_execution_logs").docs) == 1
    assert completed["status"] == "completed"
    assert completed["final_action_taken"] == "analyzed"
    # started_at from the first write is preserved (the update did not set it).
    assert completed["started_at"] is not None


def test_post_rejects_invalid_status(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_agent_logs.upsert_agent_log(
            routes_agent_logs.AgentLogUpsert(run_id="run-1", anomaly_id="ANOM-1", status="bogus")
        )
    assert err.value.status_code == 400


def test_get_filters_by_anomaly_id(fake_db):
    routes_agent_logs.upsert_agent_log(
        routes_agent_logs.AgentLogUpsert(run_id="run-1", anomaly_id="ANOM-1", status="completed")
    )
    routes_agent_logs.upsert_agent_log(
        routes_agent_logs.AgentLogUpsert(run_id="run-2", anomaly_id="ANOM-2", status="completed")
    )

    rows = routes_agent_logs.list_agent_logs(
        anomaly_id="ANOM-1", run_id=None, status=None, limit=50
    )
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-1"
    assert all("_id" not in r for r in rows)
