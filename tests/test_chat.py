"""Unit tests for the Plant Assistant chat endpoint + context gathering.

The LLM call is monkeypatched out — these assert the snapshot gathering, prompt
assembly, graceful fallbacks, and the thin router contract, with no network/key.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ingestor_service.api import chat as routes_chat
from ingestor_service.services import chat as chat_service

from tests.fakes import FakeDB


@pytest.fixture
def fake_db(monkeypatch):
    now = datetime.now(timezone.utc)
    db = FakeDB()
    db.add_collection(
        "sensors",
        [
            {
                "_id": "s1",
                "sensor_id": "MILL-01-BRG",
                "equipment_id": "MILL-01",
                "equipment_type": "trunnion_bearing",
                "metric_type": "environment",
                "is_active": True,
                "sim_stress": 0.2,
            },
            {
                "_id": "s2",
                "sensor_id": "MILL-01-VIB",
                "equipment_id": "MILL-01",
                "equipment_type": "girth_gear",
                "metric_type": "vibration",
                "is_active": True,
            },
        ],
    )
    db.add_collection(
        "telemetry_history",
        [
            {"_id": "t1", "sensor_id": "MILL-01-BRG", "timestamp_utc": now - timedelta(minutes=9),
             "reading": {"metric_type": "environment", "temp_celsius": 55.0}},
            {"_id": "t2", "sensor_id": "MILL-01-BRG", "timestamp_utc": now - timedelta(minutes=1),
             "reading": {"metric_type": "environment", "temp_celsius": 68.5}},
        ],
    )
    db.add_collection(
        "system_metadata",
        [
            {"_id": "c1", "config_type": "anomaly_thresholds", "target_metric": "temp_celsius",
             "rules": {"max_allowed_temp_celsius": 70.0}},
            {"_id": "c2", "config_type": "severity_bands", "target_metric": "*", "rules": {}},
        ],
    )
    db.add_collection(
        "anomalies",
        [
            {"_id": "a1", "anomaly_id": "ANOM-1", "status": "assigned", "severity_type": "high",
             "error_code": "BEARING_TEMP_HIGH", "sensor_id": "MILL-01-BRG", "equipment_id": "MILL-01",
             "timestamp_utc": now, "trigger_value": {"metric": "temp_celsius", "observed": 72.0, "limit": 70.0},
             "assigned_to_employee_id": "EMP-1", "recommended_solution": "Inspect lube-oil flow."},
        ],
    )
    db.add_collection(
        "staff_on_call",
        [
            {"_id": "e1", "employee_id": "EMP-1", "name": "Dana Ops", "role": "senior",
             "is_active": True, "is_on_call": True, "specialization": ["vibration"],
             "handled_severity_type": "high", "escalation_rank": 1, "email": "dana@plant.io"},
            {"_id": "e2", "employee_id": "EMP-9", "name": "Inactive Person", "role": "staff",
             "is_active": False, "is_on_call": False, "specialization": [], "escalation_rank": 9},
        ],
    )
    db.add_collection(
        "knowledge_base",
        [
            {"_id": "k1", "document_id": "seed-001", "section_title": "Bearing overheating SOP",
             "equipment_type": "trunnion_bearing", "text_content": "If bearing temp exceeds 70C, check lubrication.",
             "is_active": True, "ingested_at_utc": now - timedelta(days=1)},
            {"_id": "k2", "document_id": "fb-abc", "section_title": "Field resolution: BEARING_TEMP_HIGH",
             "text_content": "Replaced clogged lube filter; temp normalised.", "is_active": False,
             "curation_status": "pending", "ingested_at_utc": now},
        ],
    )
    monkeypatch.setattr(chat_service, "col", db)
    return db


def test_gather_pulls_every_collection(fake_db):
    ctx = chat_service.gather_factory_context()
    assert [s["sensor_id"] for s in ctx["sensors"]] == ["MILL-01-BRG", "MILL-01-VIB"]
    # latest reading is the most recent one (68.5, not 55.0)
    brg = ctx["sensors"][0]
    assert brg["_latest_reading"]["reading"]["temp_celsius"] == 68.5
    # thresholds filtered to anomaly_thresholds only
    assert len(ctx["thresholds"]) == 1
    assert ctx["thresholds"][0]["target_metric"] == "temp_celsius"
    assert [a["anomaly_id"] for a in ctx["anomalies"]] == ["ANOM-1"]
    # staff is active-only; knowledge is active-only; feedback includes pending fb-*
    assert [p["employee_id"] for p in ctx["staff"]] == ["EMP-1"]
    assert [d["document_id"] for d in ctx["knowledge"]] == ["seed-001"]
    assert [d["document_id"] for d in ctx["feedback"]] == ["fb-abc"]


def test_render_context_includes_key_facts(fake_db):
    text = chat_service.render_context(chat_service.gather_factory_context())
    assert "PLANT SNAPSHOT" in text
    assert "MILL-01-BRG" in text
    assert "temp_celsius=68.5" in text          # latest reading rendered
    assert "max_allowed_temp_celsius" in text   # threshold rendered
    assert "ANOM-1" in text and "BEARING_TEMP_HIGH" in text
    assert "Dana Ops" in text and "dana@plant.io" in text
    assert "Bearing overheating SOP" in text
    assert "Replaced clogged lube filter" in text  # feedback rendered


def test_answer_without_key_returns_not_configured(fake_db, monkeypatch):
    monkeypatch.setattr(chat_service.config, "llm_api_key", lambda: "")
    out = chat_service.answer("anything")
    assert out == chat_service._NO_KEY_REPLY


def test_answer_builds_prompt_and_forwards_history(fake_db, monkeypatch):
    monkeypatch.setattr(chat_service.config, "llm_api_key", lambda: "test-key")
    captured: dict = {}

    def _fake_call(messages):
        captured["messages"] = messages
        return "Bearing is at **68.5°C**, below the 70°C limit."

    monkeypatch.setattr(chat_service, "_call_llm", _fake_call)

    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "system", "content": "should be dropped"},  # non user/assistant filtered out
    ]
    out = chat_service.answer("Is the bearing too hot?", history)
    assert out.startswith("Bearing is at")

    msgs = captured["messages"]
    assert msgs[0]["role"] == "system" and "PLANT SNAPSHOT" in msgs[0]["content"]
    assert "MILL-01-BRG" in msgs[0]["content"]
    # forwarded history keeps only user/assistant, in order, then the new message last
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "user"]
    assert msgs[-1]["content"] == "Is the bearing too hot?"


def test_answer_llm_error_is_graceful(fake_db, monkeypatch):
    monkeypatch.setattr(chat_service.config, "llm_api_key", lambda: "test-key")

    def _boom(messages):
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(chat_service, "_call_llm", _boom)
    out = chat_service.answer("anything")
    assert out == chat_service._ERROR_REPLY


def test_fmt_ts_renders_madrid_local_time():
    from datetime import datetime, timezone

    dt = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)
    out = chat_service._fmt_ts(dt)
    if chat_service._DISPLAY_TZ is not None:
        # Europe/Madrid is UTC+2 in June (CEST): 12:00Z → 14:00+02:00.
        assert out == "2026-06-23T14:00:00+02:00"
    else:  # tzdata unavailable → graceful UTC fallback
        assert out == "2026-06-23T12:00:00+00:00"


def test_router_returns_reply(monkeypatch):
    monkeypatch.setattr(routes_chat.chat_service, "answer", lambda message, history: f"echo:{message}")
    req = routes_chat.ChatRequest(message="hello", history=[{"role": "user", "content": "prior"}])
    resp = routes_chat.chat(req)
    assert resp.reply == "echo:hello"
