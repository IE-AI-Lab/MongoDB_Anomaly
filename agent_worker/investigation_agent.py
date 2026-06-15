import json
import re
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
- HOWEVER, if the knowledge base returns an explicit operational instruction,
  standard operating procedure, or escalation rule that applies to this anomaly
  (for example "if temperature is high, contact <person>"), you MUST follow it.
  Reflect that instruction in your `recommended_solution`, and when it names a
  specific person, look them up via the staff endpoint and set
  `recommended_employee_id` to that on-call employee. A retrieved procedure that
  names who to contact takes precedence over generic troubleshooting advice — even
  if you also suspect a sensor fault, still state the required contact/escalation.
- Keep the tool loop efficient. Do not call more tools than needed.

Your FINAL message MUST be a single raw JSON object and NOTHING else — no prose,
no commentary, no markdown, no ```json code fences. Just the object:

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
    if not config.llm_api_key():
        return None

    try:
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent
    except ImportError:
        return None

    # OpenAI-compatible client so any provider works via LLM_BASE_URL (DeepSeek by
    # default; Groq/OpenAI/etc. by overriding the env). max_retries handles
    # transient rate-limits with backoff.
    llm = ChatOpenAI(
        model=config.chat_model(),
        temperature=0,
        api_key=config.llm_api_key(),
        base_url=config.llm_base_url(),
        max_retries=5,
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


def _extract_json(text: Any) -> dict[str, Any] | None:
    """Pull the decision JSON object out of the agent's final message.

    Models (DeepSeek included) wrap the JSON in a prose preamble and/or a
    ```json fenced block instead of returning a bare object, so a strict
    json.loads on the whole message fails. Try, in order: the raw text, a fenced
    code block, then the first balanced { ... } span.
    """
    if not isinstance(text, str):
        return None

    candidates: list[str] = [text.strip()]

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))

    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


_COERCE_KEYS = (
    "decision, severity, confidence, rag_query_used, staff_lookup_used, "
    "description, recommended_solution, recommended_employee_id, similar_cases, reasoning"
)


def _coerce_final_json(text: str) -> dict[str, Any] | None:
    """Last-resort: ask the LLM (in forced json_object mode) to turn a prose final
    answer into the required object. Models sometimes return analysis prose after a
    long tool loop instead of JSON; this small no-tools call reliably recovers it."""
    if not config.llm_api_key() or not isinstance(text, str) or not text.strip():
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None
    try:
        llm = ChatOpenAI(
            model=config.chat_model(),
            temperature=0,
            api_key=config.llm_api_key(),
            base_url=config.llm_base_url(),
            max_retries=3,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        prompt = (
            "Convert the analysis below into a single JSON object with exactly these "
            f"keys: {_COERCE_KEYS}. Output ONLY the JSON object.\n\nAnalysis:\n{text}"
        )
        resp = llm.invoke(prompt)
        return _extract_json(resp.content)
    except Exception:  # noqa: BLE001 — coercion is best-effort
        return None


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


def _clean_cases(cases: Any) -> list[Any]:
    """Drop empty placeholder cases the LLM tends to invent (objects with no
    text/title/id, or blank strings)."""
    if not isinstance(cases, list):
        return []
    out: list[Any] = []
    for c in cases:
        if isinstance(c, str):
            if c.strip():
                out.append(c)
        elif isinstance(c, dict):
            if c.get("text_content") or c.get("section_title") or c.get("document_id"):
                out.append(c)
    return out


def _enrich_from_tool_messages(decision: dict[str, Any], messages: list[Any]) -> dict[str, Any]:
    enriched = dict(decision)
    rag_results: list[Any] | None = None
    rag_query: str | None = None

    for message in messages:
        payload = _load_tool_payload(message)
        if not payload:
            continue

        name = _tool_name(message)
        if name == "query_rag_knowledge_base":
            rag_query = rag_query or payload.get("query_used")
            results = payload.get("results")
            if results:
                rag_results = results

        if name == "get_staff_contact":
            enriched["staff_lookup_used"] = True
            candidates = payload.get("staff_candidates") or []
            if candidates and not enriched.get("recommended_employee_id"):
                enriched["recommended_employee_id"] = candidates[0].get("employee_id")

    if rag_query and not enriched.get("rag_query_used"):
        enriched["rag_query_used"] = rag_query

    # similar_cases ALWAYS come from the actual RAG tool output — the LLM fills the
    # field with empty placeholders, so never trust its version. Fall back to
    # cleaning the LLM's list (removing empties) only when no RAG tool ran.
    if rag_results is not None:
        enriched["similar_cases"] = rag_results
    else:
        enriched["similar_cases"] = _clean_cases(enriched.get("similar_cases"))

    return enriched


def run_investigation_agent(
    anomaly: dict[str, Any],
    sensor: dict[str, Any],
    readings: list[dict[str, Any]],
    run_id: str | None = None,
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
        tags = ["anomaly-investigation"]
        error_code = anomaly.get("error_code")
        if error_code:
            tags.append(str(error_code))

        result = agent_app.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": user_message,
                    }
                ]
            },
            config={
                # The ReAct loop spends ~2 graph steps per tool call; the agent
                # usually calls 4-5 tools (memory, alerts, RAG, staff, readings).
                # Too low a limit cuts it off mid-investigation, and the coercion
                # step then emits a degenerate "please provide more details" result.
                "recursion_limit": 20,
                "run_name": "investigation_agent",
                "tags": tags,
                "metadata": {
                    "anomaly_id": anomaly.get("anomaly_id"),
                    "sensor_id": anomaly.get("sensor_id"),
                    "error_code": anomaly.get("error_code"),
                    "run_id": run_id,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 — Groq/network errors should not fail the job
        fallback = _fallback_decision(anomaly)
        fallback["reasoning"] = f"Investigation agent failed: {exc}"
        # The key IS configured here (agent_app was built), so don't blame it —
        # this path is a Groq rate-limit (429) / network / recursion error.
        fallback["recommended_solution"] = (
            "Automated investigation could not complete (LLM rate-limit or error). "
            "Review the anomaly manually; see the agent worker logs for details."
        )
        return fallback

    messages = result["messages"]
    final_message = messages[-1].content

    decision = _extract_json(final_message) or _coerce_final_json(final_message)
    if decision is not None:
        return _enrich_from_tool_messages(decision, messages)

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
