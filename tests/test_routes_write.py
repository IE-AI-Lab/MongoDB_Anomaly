"""Unit tests for write routes lifecycle and side effects."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from ingestor_service.api import write as routes_write

from tests.fakes import FakeDB


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    now = datetime.now(timezone.utc)
    db.add_collection(
        "anomalies",
        [
            {
                "_id": "mongo-anom-1",
                "anomaly_id": "ANOM-1",
                "status": "unresolved",
                "assigned_to_employee_id": None,
                "updated_at_utc": now,
            },
            {
                "_id": "mongo-anom-2",
                "anomaly_id": "ANOM-2",
                "status": "analyzed",
                "updated_at_utc": now,
            },
            {
                "_id": "mongo-anom-3",
                "anomaly_id": "ANOM-3",
                "status": "resolved",
                "assigned_to_employee_id": "EMP-2",
                "updated_at_utc": now,
            },
        ],
    )
    db.add_collection(
        "staff_on_call",
        [
            {"_id": "mongo-emp-1", "employee_id": "EMP-1", "is_on_call": True},
            {"_id": "mongo-emp-2", "employee_id": "EMP-2", "is_on_call": False},
        ],
    )
    monkeypatch.setattr(routes_write, "col", db)
    monkeypatch.setattr(
        routes_write,
        "embed_resolution_into_knowledge",
        lambda **kwargs: "fb-test-doc-1",
    )
    return db


def test_patch_allows_forward_transition_to_analyzed(fake_db):
    result = routes_write.patch_anomaly(
        "ANOM-1",
        routes_write.AnalysisPatch(
            description="Likely bearing wear",
            recommended_solution="Schedule inspection",
            status="analyzed",
        ),
    )
    assert result["status"] == "analyzed"
    assert result["description"] == "Likely bearing wear"
    assert "_id" not in result


def test_patch_rejects_assigned_or_resolved_status(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_write.patch_anomaly("ANOM-1", routes_write.AnalysisPatch(status="assigned"))
    assert err.value.status_code == 409


def test_patch_rejects_backward_transition(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_write.patch_anomaly("ANOM-2", routes_write.AnalysisPatch(status="unresolved"))
    assert err.value.status_code == 409


def test_assign_sets_assignee_and_flips_on_call_flag(fake_db):
    result = routes_write.assign_anomaly("ANOM-1", routes_write.AssignRequest(employee_id="EMP-1"))
    assert result["status"] == "assigned"
    assert result["assigned_to_employee_id"] == "EMP-1"

    staff = fake_db("staff_on_call").find_one({"employee_id": "EMP-1"})
    assert staff is not None
    assert staff["is_on_call"] is False


def test_assign_rejects_already_assigned_anomaly(fake_db):
    # First assignment moves ANOM-1 to assigned.
    routes_write.assign_anomaly("ANOM-1", routes_write.AssignRequest(employee_id="EMP-1"))
    with pytest.raises(HTTPException) as err:
        routes_write.assign_anomaly("ANOM-1", routes_write.AssignRequest(employee_id="EMP-1"))
    assert err.value.status_code == 409


def test_resolve_fixed_adds_knowledge_document_and_releases_staff(fake_db):
    # Move ANOM-1 through assign first so resolver defaults to assignee.
    routes_write.assign_anomaly("ANOM-1", routes_write.AssignRequest(employee_id="EMP-1"))
    result = routes_write.resolve_anomaly(
        "ANOM-1",
        routes_write.ResolveRequest(
            outcome="fixed",
            resolution_notes="Replaced worn bearing and rebalanced shaft",
        ),
    )
    assert result["status"] == "resolved"
    assert result["knowledge_document_id"] == "fb-test-doc-1"
    assert result["resolved_by"] == "EMP-1"

    staff = fake_db("staff_on_call").find_one({"employee_id": "EMP-1"})
    assert staff is not None
    assert staff["is_on_call"] is True


def test_resolve_rejects_already_resolved(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_write.resolve_anomaly(
            "ANOM-3",
            routes_write.ResolveRequest(outcome="fixed", resolution_notes="noop"),
        )
    assert err.value.status_code == 409
