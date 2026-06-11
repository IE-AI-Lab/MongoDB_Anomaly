"""Tests for investigation agent helpers (no live Groq / LangGraph compile)."""

from __future__ import annotations

from agent_worker.investigation_agent import _enrich_from_tool_messages, _fallback_decision


def test_fallback_decision_includes_error_code():
    decision = _fallback_decision(
        {
            "error_code": "TEMP_HIGH",
            "sensor_id": "SENS-1",
            "trigger_value": {"metric": "temp_celsius", "observed": 28, "limit": 24},
            "severity_type": "medium",
        }
    )
    assert "TEMP_HIGH" in decision["description"]
    assert decision["decision"] == "alert"


def test_enrich_from_tool_messages():
    class Msg:
        def __init__(self, name: str, content: str):
            self.name = name
            self.content = content

    decision = {"description": "x", "recommended_solution": "y"}
    messages = [
        Msg(
            "query_rag_knowledge_base",
            '{"query_used": "pump vibration", "results": [{"section_title": "Case A"}]}',
        ),
        Msg(
            "get_staff_contact",
            '{"staff_candidates": [{"employee_id": "EMP-002"}]}',
        ),
    ]
    enriched = _enrich_from_tool_messages(decision, messages)
    assert enriched["rag_query_used"] == "pump vibration"
    assert enriched["recommended_employee_id"] == "EMP-002"
    assert enriched["staff_lookup_used"] is True
