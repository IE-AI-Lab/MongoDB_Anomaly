import json
from typing import Any

from . import config
from .agent_tools import (
    get_sensor_readings,
    get_staff_contact,
    query_rag_knowledge_base,
    retrieve_machine_memory,
    retrieve_recent_alerts,
)

agent_tools = [
    query_rag_knowledge_base,
    get_staff_contact,
    get_sensor_readings,
    retrieve_recent_alerts,
    retrieve_machine_memory,
]

SYSTEM_PROMPT = """
You are an autonomous anomaly investigation agent.

You operate in a loop:
1. Inspect the current sensor data and rule-based signal.
2. Decide what information is missing.
3. Call tools when useful.
4. Observe the tool results.
5. Decide whether more tool calls are needed.
6. Return a final JSON decision.

You have tools for:
- writing and sending your own RAG query to the backend /knowledge/search endpoint
- fetching more telemetry (get_sensor_readings) when bootstrap readings are insufficient
- retrieving previous alerts
- retrieving persistent machine memory (sensor + readings + past anomalies)
- calling the backend /staff_on_call endpoint

Important behavior:
- You should usually retrieve machine memory and recent alerts before making a final decision.
- You must call the RAG tool at least once. You decide the query text.
- You must call the staff endpoint when recommending a human assignee.
- Do not blindly trust the hardcoded rule signal. Treat it as one piece of evidence.
- Keep the tool loop efficient. Do not call more tools than needed.

Final response must be valid JSON only:

{
  "decision": "ignore | monitor | alert | escalate",
  "severity": "normal | low | medium | high | critical",
  "confidence": 0.0,
  "rag_query_used": "query string or null",
  "staff_lookup_used": true,
  "description": "analysis to store on the anomaly",
  "recommended_solution": "recommended human action",
  "recommended_employee_id": "employee id or null",
  "similar_cases": [],
  "reasoning": "short reasoning summary"
}
"""

def _build_agent_app():
    if not config.groq_api_key():
        return None

    try:
        from langchain_groq import ChatGroq
        from langgraph.prebuilt import create_react_agent
    except ImportError:
        return None

    llm = ChatGroq(
        model=config.chat_model(),
        temperature=0,
        groq_api_key=config.groq_api_key(),
        groq_api_base=config.groq_native_api_base(),
    )
    return create_react_agent(
        model=llm,
        tools=agent_tools,
        prompt=SYSTEM_PROMPT,
    )


def _fallback_decision(anomaly: dict[str, Any]) -> dict[str, Any]:
    trigger = anomaly.get("trigger_value") or {}
    metric = trigger.get("metric") or anomaly.get("metric_type", "metric")
    observed = trigger.get("observed", "unknown")
    limit = trigger.get("limit", "unknown")
    error_code = anomaly.get("error_code", "ANOMALY")
    equipment_id = anomaly.get("equipment_id") or anomaly.get("sensor_id", "equipment")
    severity = anomaly.get("severity_type", "medium")

    return {
        "decision": "alert",
        "severity": severity,
        "confidence": 0.5,
        "rag_query_used": None,
        "staff_lookup_used": False,
        "description": (
            f"{error_code} detected on {equipment_id}: {metric} observed {observed} "
            f"against limit {limit}."
        ),
        "recommended_solution": (
            "Review the anomaly manually or configure GROQ_API_KEY so the "
            "investigation agent can call RAG and staff tools."
        ),
        "recommended_employee_id": None,
        "similar_cases": [],
        "reasoning": "GROQ_API_KEY or LangChain/Groq dependencies are not configured; agent did not run.",
    }


def _load_tool_payload(message: Any) -> dict[str, Any] | None:
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _tool_name(message: Any) -> str:
    return getattr(message, "name", "") or getattr(message, "tool", "")


def _enrich_from_tool_messages(decision: dict[str, Any], messages: list[Any]) -> dict[str, Any]:
    enriched = dict(decision)

    for message in messages:
        payload = _load_tool_payload(message)
        if not payload:
            continue

        name = _tool_name(message)
        if name == "query_rag_knowledge_base":
            if not enriched.get("rag_query_used"):
                enriched["rag_query_used"] = payload.get("query_used")
            if not enriched.get("similar_cases"):
                enriched["similar_cases"] = payload.get("results", [])

        if name == "get_staff_contact":
            enriched["staff_lookup_used"] = True
            candidates = payload.get("staff_candidates") or []
            if candidates and not enriched.get("recommended_employee_id"):
                enriched["recommended_employee_id"] = candidates[0].get("employee_id")

    return enriched


def run_investigation_agent(
    anomaly: dict[str, Any],
    sensor: dict[str, Any],
    readings: list[dict[str, Any]],
) -> dict[str, Any]:
    agent_app = _build_agent_app()
    if agent_app is None:
        return _fallback_decision(anomaly)

    user_message = f"""
Anomaly:
{json.dumps(anomaly, default=str)}

Sensor metadata:
{json.dumps(sensor, default=str)}

Recent readings (bootstrap — call retrieve_machine_memory or get_sensor_readings for more):
{json.dumps(readings[-10:], default=str)}

Investigate this event using the available tools. You must write your own RAG
query and call query_rag_knowledge_base. If you recommend an assignee, call
get_staff_contact with the best specialization/severity/facility filters.
Call retrieve_machine_memory, retrieve_recent_alerts, or get_sensor_readings
when you need more history than the bootstrap readings above.
Return final JSON only.
"""

    try:
        result = agent_app.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": user_message,
                    }
                ]
            },
            config={"recursion_limit": 8},
        )
    except Exception as exc:  # noqa: BLE001 — Groq/network errors should not fail the job
        fallback = _fallback_decision(anomaly)
        fallback["reasoning"] = f"Investigation agent failed: {exc}"
        return fallback

    messages = result["messages"]
    final_message = messages[-1].content

    try:
        decision = json.loads(final_message)
        if not isinstance(decision, dict):
            raise json.JSONDecodeError("agent output was not a JSON object", final_message, 0)
        return _enrich_from_tool_messages(decision, messages)
    except json.JSONDecodeError:
        fallback = _fallback_decision(anomaly)
        fallback.update({
            "decision": "alert",
            "severity": anomaly.get("severity_type", "medium"),
            "confidence": 0.5,
            "rag_query_used": None,
            "staff_lookup_used": False,
            "reasoning": final_message,
            "recommended_solution": "Review manually because the agent returned non-JSON output.",
        })
        return fallback
