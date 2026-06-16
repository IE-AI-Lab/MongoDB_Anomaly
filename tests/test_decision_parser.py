"""Unit tests for agent_worker.decision_parser — the messy-LLM-output recovery
pipeline. No live LLM: extract_json handles the JSON directly, so coerce (which
needs a key) is never reached in these cases."""

from __future__ import annotations

from agent_worker import decision_parser as dp


class _Msg:
    def __init__(self, name: str, content: str):
        self.name = name
        self.content = content


# --- extract_json ----------------------------------------------------------


def test_extract_json_bare_object():
    assert dp.extract_json('{"decision": "alert"}') == {"decision": "alert"}


def test_extract_json_from_fenced_block_with_prose():
    text = 'Here is my answer:\n```json\n{"decision": "escalate", "confidence": 0.9}\n```\nDone.'
    assert dp.extract_json(text) == {"decision": "escalate", "confidence": 0.9}


def test_extract_json_handles_nested_object_in_fence():
    # Greedy capture must keep the whole balanced object, not stop at the first }.
    text = '```json\n{"a": {"b": 1}, "decision": "monitor"}\n```'
    assert dp.extract_json(text) == {"a": {"b": 1}, "decision": "monitor"}


def test_extract_json_from_prose_braces_span():
    text = 'I think the answer is {"decision": "ignore"} based on the data.'
    assert dp.extract_json(text) == {"decision": "ignore"}


def test_extract_json_returns_none_for_non_json():
    assert dp.extract_json("no json here at all") is None
    assert dp.extract_json(None) is None
    assert dp.extract_json(["not", "a", "string"]) is None


def test_extract_json_rejects_non_dict_json():
    assert dp.extract_json("[1, 2, 3]") is None


# --- enrich_from_tool_messages: similar_cases precedence -------------------


def test_similar_cases_always_come_from_rag_tool_not_llm():
    # LLM invented placeholder cases; the real RAG results must win.
    decision = {"similar_cases": [{"section_title": "LLM made this up"}]}
    messages = [
        _Msg(
            "query_rag_knowledge_base",
            '{"query_used": "pump vibration", "results": [{"document_id": "kb-1"}]}',
        )
    ]
    enriched = dp.enrich_from_tool_messages(decision, messages)
    assert enriched["similar_cases"] == [{"document_id": "kb-1"}]
    assert enriched["rag_query_used"] == "pump vibration"


def test_similar_cases_cleaned_when_no_rag_tool_ran():
    # No RAG tool: keep the LLM's list but drop empty placeholders.
    decision = {
        "similar_cases": [
            {"section_title": "Real case"},
            {"foo": "bar"},  # no text/title/id -> dropped
            "  ",  # blank string -> dropped
            "a useful string case",
        ]
    }
    enriched = dp.enrich_from_tool_messages(decision, [])
    assert enriched["similar_cases"] == [
        {"section_title": "Real case"},
        "a useful string case",
    ]


def test_enrich_sets_staff_lookup_and_employee_id():
    decision: dict = {}
    messages = [_Msg("get_staff_contact", '{"staff_candidates": [{"employee_id": "EMP-009"}]}')]
    enriched = dp.enrich_from_tool_messages(decision, messages)
    assert enriched["staff_lookup_used"] is True
    assert enriched["recommended_employee_id"] == "EMP-009"


# --- parse_decision --------------------------------------------------------


def test_parse_decision_extracts_and_enriches():
    final = '```json\n{"decision": "alert", "similar_cases": []}\n```'
    messages = [
        _Msg("query_rag_knowledge_base", '{"query_used": "q", "results": [{"document_id": "kb-2"}]}'),
    ]
    out = dp.parse_decision(final, messages)
    assert out is not None
    assert out["decision"] == "alert"
    assert out["similar_cases"] == [{"document_id": "kb-2"}]
    assert out["rag_query_used"] == "q"


def test_parse_decision_returns_none_for_unparseable(monkeypatch):
    # No API key -> coerce_final_json short-circuits to None, so a non-JSON final
    # message yields None and the caller applies its own fallback.
    monkeypatch.setattr(dp.config, "llm_api_key", lambda: "")
    assert dp.parse_decision("sorry, I could not finish", []) is None
