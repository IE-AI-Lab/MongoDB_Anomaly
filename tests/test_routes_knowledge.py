"""Unit tests for the knowledge_base CRUD / curation endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from ingestor_service.api import knowledge as routes_knowledge

from tests.fakes import FakeDB


NOW = datetime.now(timezone.utc)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    db.add_collection(
        "knowledge_base",
        [
            {
                "_id": "mongo-kb-1",
                "document_id": "seed-000",
                "source_file": "scripts/knowledge_seed.py:KNOWLEDGE_SEED",
                "section_title": "Pump bearing vibration above 4.5 mm/s",
                "equipment_type": "centrifugal_pump",
                "associated_error_codes": ["VIBRATION_HIGH"],
                "text_content": "Sustained vibration indicates bearing wear.",
                "chunk_index": 0,
                "is_active": True,
                "ingested_at_utc": NOW - timedelta(days=1),
                "schema_version": 1,
            },
            {
                "_id": "mongo-kb-2",
                "document_id": "fb-1234",
                "source_file": "anomaly:ANOM-1",
                "section_title": "Field resolution: VIBRATION_HIGH",
                "equipment_type": "centrifugal_pump",
                "associated_error_codes": ["VIBRATION_HIGH"],
                "text_content": "Tightened the coupling; vibration returned to normal.",
                "chunk_index": 0,
                "is_active": False,
                "ingested_at_utc": NOW,
                "schema_version": 1,
                "source_metadata": {"type": "field_feedback", "anomaly_id": "ANOM-1"},
            },
        ],
    )
    monkeypatch.setattr(routes_knowledge, "col", db)
    return db


def _list(**overrides):
    """Call list_knowledge with all Query-default params passed explicitly."""
    params = dict(is_active=None, equipment_type=None, source=None, limit=50, skip=0)
    params.update(overrides)
    return routes_knowledge.list_knowledge(**params)


def test_list_returns_all_without_filters(fake_db):
    rows = _list()
    assert len(rows) == 2
    assert all("_id" not in r for r in rows)
    # Sorted ingested_at_utc desc — the newer feedback doc comes first.
    assert rows[0]["document_id"] == "fb-1234"


def test_review_queue_filter(fake_db):
    rows = _list(is_active=False, source="feedback")
    assert len(rows) == 1
    assert rows[0]["document_id"] == "fb-1234"


def test_list_filters_by_equipment_type(fake_db):
    assert len(_list(equipment_type="centrifugal_pump")) == 2
    assert _list(equipment_type="coolant_loop") == []


def test_list_skip_and_limit(fake_db):
    assert len(_list(limit=1)) == 1
    rows = _list(skip=1)
    assert len(rows) == 1
    assert rows[0]["document_id"] == "seed-000"


def test_list_rejects_unknown_source(fake_db):
    with pytest.raises(HTTPException) as err:
        _list(source="bogus")
    assert err.value.status_code == 400


def test_get_by_id(fake_db):
    doc = routes_knowledge.get_knowledge("seed-000")
    assert doc["section_title"].startswith("Pump bearing")
    assert "_id" not in doc


def test_get_missing_returns_404(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_knowledge.get_knowledge("nope")
    assert err.value.status_code == 404


def test_create_fills_server_fields(fake_db):
    doc = routes_knowledge.create_knowledge(
        routes_knowledge.KnowledgeCreate(
            section_title="Manual note",
            text_content="Check the unloader valve first.",
            equipment_type="hydraulic_line",
        )
    )
    assert doc["document_id"].startswith("kb-")
    assert doc["source_file"] == "manual"
    assert doc["is_active"] is True
    assert doc["chunk_index"] == 0
    assert doc["schema_version"] == 1
    assert doc["ingested_at_utc"] is not None
    assert "_id" not in doc
    assert len(fake_db("knowledge_base").docs) == 3


def test_patch_approves_feedback_entry(fake_db):
    doc = routes_knowledge.patch_knowledge(
        "fb-1234", routes_knowledge.KnowledgePatch(is_active=True)
    )
    assert doc["is_active"] is True
    assert doc["updated_at_utc"] is not None
    # Persisted, not just echoed.
    stored = fake_db("knowledge_base").find_one({"document_id": "fb-1234"})
    assert stored["is_active"] is True


def test_patch_empty_returns_400(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_knowledge.patch_knowledge("fb-1234", routes_knowledge.KnowledgePatch())
    assert err.value.status_code == 400


def test_patch_missing_returns_404(fake_db):
    with pytest.raises(HTTPException) as err:
        routes_knowledge.patch_knowledge(
            "nope", routes_knowledge.KnowledgePatch(is_active=True)
        )
    assert err.value.status_code == 404


def test_delete_then_redelete_404(fake_db):
    result = routes_knowledge.delete_knowledge("fb-1234")
    assert result == {"deleted": True, "document_id": "fb-1234"}
    assert len(fake_db("knowledge_base").docs) == 1

    with pytest.raises(HTTPException) as err:
        routes_knowledge.delete_knowledge("fb-1234")
    assert err.value.status_code == 404
