from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent_worker.investigation_agent import run_investigation_agent


@dataclass
class _FakeMessage:
    content: str
    name: str = ""


class _FakeAgentApp:
    def __init__(self, final_payload: dict[str, Any]):
        self.final_payload = final_payload

    def invoke(self, _inputs: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        assert config is not None
        assert config.get("recursion_limit") == 8
        return {
            "messages": [
                _FakeMessage(
                    name="query_rag_knowledge_base",
                    content=json.dumps(
                        {
                            "query_used": "pump vibration bearing wear",
                            "results": [{"section_title": "Pump bearing vibration above 4.5 mm/s"}],
                        }
                    ),
                ),
                _FakeMessage(
                    name="get_staff_contact",
                    content=json.dumps({"staff_candidates": [{"employee_id": "EMP-002"}]}),
                ),
                _FakeMessage(content=json.dumps(self.final_payload)),
            ]
        }


def test_investigation_agent_output_has_expected_shape(monkeypatch):
    final_payload = {
        "decision": "alert",
        "severity": "high",
        "confidence": 0.92,
        "rag_query_used": None,
        "staff_lookup_used": False,
        "description": "Vibration is sustained and consistent with bearing wear.",
        "recommended_solution": "Schedule bearing replacement in next maintenance window.",
        "recommended_employee_id": None,
        "similar_cases": [],
        "reasoning": "RAG + readings indicate likely bearing degradation.",
    }
    monkeypatch.setattr(
        "agent_worker.investigation_agent._build_agent_app",
        lambda: _FakeAgentApp(final_payload),
    )

    result = run_investigation_agent(
        anomaly={
            "anomaly_id": "ANOM-123",
            "sensor_id": "SENS-9",
            "error_code": "VIBRATION_HIGH",
            "severity_type": "high",
        },
        sensor={"sensor_id": "SENS-9", "equipment_type": "centrifugal_pump"},
        readings=[{"timestamp_utc": "2026-01-01T00:00:00Z", "amplitude_mm": 5.2}],
    )

    expected_keys = {
        "decision",
        "severity",
        "confidence",
        "rag_query_used",
        "staff_lookup_used",
        "description",
        "recommended_solution",
        "recommended_employee_id",
        "similar_cases",
        "reasoning",
    }
    assert expected_keys.issubset(result.keys())
    assert result["description"].strip()
    assert result["recommended_solution"].strip()
    assert result["rag_query_used"] == "pump vibration bearing wear"
    assert result["staff_lookup_used"] is True
    assert result["recommended_employee_id"] == "EMP-002"
