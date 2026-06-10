"""Unit tests for the RAG curation endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from ingestor_service import routes_curation

from tests.fakes import FakeDB


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    now = datetime.now(timezone.utc)
    db.add_collection(
        "knowledge_base",
        [
            {
                "_id": "m1",
                "document_id": "fb-1",
                "is_active": False,
                "curation_status": "pending",
                "text_content": "Field resolution A",
                "ingested_at_utc": now,
            },
            {
                "_id": "m2",
                "document_id": "fb-2",
                "is_active": False,
                "curation_status": "pending",
                "text_content": "Field resolution B",
                "ingested_at_utc": now - timedelta(minutes=5),
            },
            {
                "_id": "m3",
                "document_id": "seed-001",
                "is_active": True,
                "curation_status": "approved",
                "text_content": "Seed doc",
                "ingested_at_utc": now - timedelta(days=1),
            },
            {
                "_id": "m4",
                "document_id": "fb-3",
                "is_active": False,
                "curation_status": "rejected",
                "text_content": "Bad note",
                "ingested_at_utc": now - timedelta(minutes=10),
            },
        ],
    )
    monkeypatch.setattr(routes_curation, "col", db)
    return db


def test_pending_lists_only_pending_docs(fake_db):
    pending = routes_curation.list_pending_knowledge(limit=50)
    ids = {d["document_id"] for d in pending}
    assert ids == {"fb-1", "fb-2"}  # excludes approved seed + rejected
    assert all("_id" not in d for d in pending)


def test_pending_sorted_newest_first(fake_db):
    pending = routes_curation.list_pending_knowledge(limit=50)
    assert [d["document_id"] for d in pending] == ["fb-1", "fb-2"]


def test_activate_makes_doc_active(fake_db):
    result = routes_curation.activate_knowledge(
        "fb-1", routes_curation.CurationAction(curator_id="alice")
    )
    assert result["is_active"] is True
    assert result["curation_status"] == "approved"
    assert result["curated_by"] == "alice"
    # and it drops out of the pending queue
    assert "fb-1" not in {d["document_id"] for d in routes_curation.list_pending_knowledge(limit=50)}


def test_activate_without_body(fake_db):
    result = routes_curation.activate_knowledge("fb-2", None)
    assert result["is_active"] is True
    assert "curated_by" not in result


def test_activate_already_active_is_409(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_curation.activate_knowledge("seed-001", None)
    assert err.value.status_code == 409


def test_activate_missing_is_404(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_curation.activate_knowledge("does-not-exist", None)
    assert err.value.status_code == 404


def test_reject_marks_rejected_and_keeps_inactive(fake_db):
    result = routes_curation.reject_knowledge(
        "fb-1", routes_curation.CurationAction(curator_id="bob", reason="duplicate")
    )
    assert result["is_active"] is False
    assert result["curation_status"] == "rejected"
    assert result["curation_reason"] == "duplicate"
    assert "fb-1" not in {d["document_id"] for d in routes_curation.list_pending_knowledge(limit=50)}


def test_reject_active_doc_is_409(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_curation.reject_knowledge("seed-001", None)
    assert err.value.status_code == 409
