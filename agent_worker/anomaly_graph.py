from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Mapping, Optional, TypedDict

import requests
from langgraph.graph import END, StateGraph

from . import config

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8000"


class AgentState(TypedDict, total=False):
    anomaly_id: str
    run_id: str
    base_url: str
    job_fields: dict[str, str]
    anomaly: dict[str, Any]
    sensor: dict[str, Any]
    readings: list[dict[str, Any]]
    knowledge: list[dict[str, Any]]
    staff_candidates: list[dict[str, Any]]
    analysis: dict[str, Any]
    patched_anomaly: dict[str, Any]
    # Tracing accumulators written into agent_execution_logs at the end.
    steps: list[dict[str, Any]]
    tokens_used: dict[str, int]
    final_action: str
    skipped: bool
    skip_reason: str


class DataLayerClient:
    """Small HTTP wrapper around the documented ingestor API."""

    def __init__(self, base_url: str | None = None, timeout_seconds: float = 30.0):
        self.base_url = (base_url or config.data_layer_base_url() or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params)

    def patch(self, path: str, body: Mapping[str, Any]) -> Any:
        return self._request("PATCH", path, json=body)

    def post(self, path: str, body: Mapping[str, Any]) -> Any:
        return self._request("POST", path, json=body)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        params = kwargs.pop("params", None)
        if params:
            kwargs["params"] = {k: v for k, v in params.items() if v is not None}

        response = requests.request(method, url, timeout=self.timeout_seconds, **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"{method} {url} failed with {response.status_code}: {response.text}"
            ) from exc
        return response.json()


def _client(state: AgentState) -> DataLayerClient:
    return DataLayerClient(state.get("base_url"))


def _anomaly_id_from(state: AgentState) -> str:
    anomaly_id = state.get("anomaly_id") or state.get("job_fields", {}).get("anomaly_id", "")
    if not anomaly_id:
        raise ValueError("anomaly_id is required to run the anomaly graph")
    return anomaly_id


# ---------------------------------------------------------------------------
# Tracing — every node is wrapped so it records a step into state["steps"].
# The finalize node ships the whole trace to /agent_logs.
# ---------------------------------------------------------------------------

def _traced(tool_name: str) -> Callable[[Callable[[AgentState], AgentState]], Callable[[AgentState], AgentState]]:
    def decorate(fn: Callable[[AgentState], AgentState]) -> Callable[[AgentState], AgentState]:
        def wrapper(state: AgentState) -> AgentState:
            steps = list(state.get("steps", []))
            index = len(steps)
            started = time.time()
            result = fn(state)  # may raise — the consumer leaves the job pending
            latency_ms = int((time.time() - started) * 1000)
            steps.append(
                {
                    "step_index": index,
                    "tool_name": tool_name,
                    "latency_ms": latency_ms,
                    "success": True,
                }
            )
            result["steps"] = steps
            return result

        return wrapper

    return decorate


def _post_log(state: AgentState, **fields: Any) -> None:
    """Best-effort write to /agent_logs. Tracing must never break a run."""
    run_id = state.get("run_id")
    if not run_id:
        return
    body = {
        "run_id": run_id,
        "anomaly_id": state.get("anomaly_id", ""),
        "agent_name": config.AGENT_NAME,
        "agent_version": config.AGENT_VERSION,
        "model_id": config.chat_model(),
        **fields,
    }
    try:
        _client(state).post("/agent_logs", body)
    except Exception as exc:  # noqa: BLE001 — observability is best-effort
        log.warning("failed to write agent_execution_logs run_id=%s: %s", run_id, exc)


@_traced("start")
def start_node(state: AgentState) -> AgentState:
    anomaly_id = _anomaly_id_from(state)
    out: AgentState = {**state, "anomaly_id": anomaly_id, "steps": state.get("steps", [])}
    _post_log(out, status="running")
    return out


@_traced("fetch_anomaly")
def fetch_anomaly_node(state: AgentState) -> AgentState:
    anomaly_id = state["anomaly_id"]
    anomaly = _client(state).get(f"/anomalies/{anomaly_id}")

    log.info("fetched anomaly %s status=%s", anomaly_id, anomaly.get("status"))
    return {**state, "anomaly": anomaly}


def route_status(state: AgentState) -> str:
    status = state["anomaly"].get("status", "unresolved")
    return "process" if status == "unresolved" else "skip"


@_traced("skip")
def skip_node(state: AgentState) -> AgentState:
    anomaly_id = state["anomaly"].get("anomaly_id", state.get("anomaly_id", ""))
    status = state["anomaly"].get("status", "unknown")
    reason = f"Anomaly {anomaly_id} is already {status}; skipping idempotently."

    log.info(reason)
    return {**state, "skipped": True, "skip_reason": reason, "final_action": f"skipped ({status})"}


@_traced("fetch_sensor")
def fetch_sensor_node(state: AgentState) -> AgentState:
    sensor_id = state["anomaly"]["sensor_id"]
    sensor = _client(state).get(f"/sensors/{sensor_id}")

    log.info("fetched sensor %s", sensor_id)
    return {**state, "sensor": sensor}


@_traced("fetch_readings")
def fetch_readings_node(state: AgentState) -> AgentState:
    sensor_id = state["anomaly"]["sensor_id"]
    readings = _client(state).get(
        f"/sensors/{sensor_id}/readings",
        minutes=60,
        limit=200,
    )

    log.info("fetched %s recent readings for %s", len(readings), sensor_id)
    return {**state, "readings": readings}


def _fault_query(anomaly: Mapping[str, Any], sensor: Mapping[str, Any]) -> str:
    trigger = anomaly.get("trigger_value") or {}
    metric = trigger.get("metric") or anomaly.get("metric_type", "metric")
    observed = trigger.get("observed", "unknown")
    limit = trigger.get("limit", "unknown")
    equipment_type = sensor.get("equipment_type") or "equipment"
    equipment_id = anomaly.get("equipment_id") or anomaly.get("sensor_id")
    error_code = anomaly.get("error_code", "anomaly")

    return (
        f"{equipment_type} {equipment_id} {error_code}: "
        f"{metric} observed {observed} with limit {limit}"
    )


@_traced("search_knowledge")
def search_knowledge_node(state: AgentState) -> AgentState:
    anomaly = state["anomaly"]
    sensor = state.get("sensor", {})
    knowledge = _client(state).get(
        "/knowledge/search",
        q=_fault_query(anomaly, sensor),
        equipment_type=sensor.get("equipment_type"),
        error_codes=anomaly.get("error_code"),
        k=5,
    )

    log.info("retrieved %s knowledge documents", len(knowledge))
    return {**state, "knowledge": knowledge}


@_traced("find_staff")
def find_staff_node(state: AgentState) -> AgentState:
    anomaly = state["anomaly"]
    metric_type = anomaly.get("metric_type")
    severity_type = anomaly.get("severity_type")
    facility_id = anomaly.get("facility_id")
    client = _client(state)

    candidates = client.get(
        "/staff_on_call",
        is_on_call="true",
        specialization=metric_type,
        handled_severity_type=severity_type,
        facility_id=facility_id,
    )

    if not candidates:
        candidates = client.get(
            "/staff_on_call",
            is_on_call="true",
            specialization=metric_type,
        )

    log.info("found %s staff candidates", len(candidates))
    return {**state, "staff_candidates": candidates}


def _compact_knowledge(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for doc in docs[:5]:
        compact.append(
            {
                "document_id": doc.get("document_id") or doc.get("knowledge_id") or doc.get("id"),
                "section_title": doc.get("section_title"),
                "equipment_type": doc.get("equipment_type"),
                "associated_error_codes": doc.get("associated_error_codes"),
                "text_content": (doc.get("text_content") or "")[:800],
            }
        )
    return compact


def _readings_trend(readings: list[dict[str, Any]]) -> str:
    if not readings:
        return "no recent readings available"
    return f"{len(readings)} readings in the last hour (oldest first to newest)"


def _baseline_analysis(
    anomaly: Mapping[str, Any],
    sensor: Mapping[str, Any],
    knowledge: list[dict[str, Any]],
) -> dict[str, str]:
    """Deterministic description/solution. Used as the LLM fallback so the worker
    still produces a useful analysis without a Groq key or on an LLM error."""
    trigger = anomaly.get("trigger_value") or {}
    metric = trigger.get("metric") or anomaly.get("metric_type", "metric")
    observed = trigger.get("observed", "unknown")
    limit = trigger.get("limit", "unknown")
    consecutive_count = trigger.get("consecutive_count", "multiple")
    error_code = anomaly.get("error_code", "ANOMALY")
    severity_type = anomaly.get("severity_type", "unknown")
    severity_level = anomaly.get("severity_level", "unknown")
    equipment_id = anomaly.get("equipment_id") or anomaly.get("sensor_id", "equipment")
    case_hint = ""
    if knowledge:
        title = knowledge[0].get("section_title") or "the top retrieved knowledge case"
        case_hint = f" Grounding: review {title}."

    description = (
        f"{error_code} detected on {equipment_id}. "
        f"{metric} is {observed} against limit {limit} after "
        f"{consecutive_count} consecutive readings. "
        f"Severity is {severity_type} at level {severity_level}.{case_hint}"
    )
    recommended_solution = (
        f"Inspect {equipment_id} for the {error_code.lower()} condition, compare the last hour "
        "of telemetry against the retrieved knowledge cases, and schedule corrective maintenance "
        "with the recommended on-call specialist."
    )
    return {"description": description, "recommended_solution": recommended_solution}


_SYSTEM_PROMPT = (
    "You are a maintenance reliability engineer for an industrial CNC fleet. "
    "Given a detected anomaly, recent telemetry context, and retrieved knowledge-base "
    "cases, write a concise root-cause analysis and a concrete recommended fix. "
    "Ground your reasoning in the provided knowledge cases when they apply. "
    'Respond ONLY with JSON: {"description": str, "recommended_solution": str}.'
)


def _llm_reason(
    anomaly: Mapping[str, Any],
    sensor: Mapping[str, Any],
    readings: list[dict[str, Any]],
    knowledge: list[dict[str, Any]],
) -> Optional[tuple[dict[str, str], dict[str, int]]]:
    """Run Groq reasoning. Returns (analysis, token_usage) or None to fall back.

    Isolated here so the agent team can iterate on the prompt without touching the
    graph wiring. Uses the OpenAI SDK against Groq's OpenAI-compatible endpoint.
    """
    api_key = config.groq_api_key()
    if not api_key:
        log.info("GROQ_API_KEY not set — using deterministic baseline analysis")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openai package not installed — using baseline analysis")
        return None

    user_payload = {
        "anomaly": {
            "error_code": anomaly.get("error_code"),
            "metric_type": anomaly.get("metric_type"),
            "severity_type": anomaly.get("severity_type"),
            "severity_level": anomaly.get("severity_level"),
            "equipment_id": anomaly.get("equipment_id") or anomaly.get("sensor_id"),
            "trigger_value": anomaly.get("trigger_value"),
        },
        "equipment_type": sensor.get("equipment_type"),
        "telemetry_trend": _readings_trend(readings),
        "knowledge_cases": _compact_knowledge(knowledge),
    }

    try:
        client = OpenAI(api_key=api_key, base_url=config.groq_base_url())
        completion = client.chat.completions.create(
            model=config.chat_model(),
            response_format={"type": "json_object"},
            temperature=0.2,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, default=str)},
            ],
        )
        content = completion.choices[0].message.content or "{}"
        parsed = json.loads(content)
        analysis = {
            "description": str(parsed.get("description", "")).strip(),
            "recommended_solution": str(parsed.get("recommended_solution", "")).strip(),
        }
        if not analysis["description"] or not analysis["recommended_solution"]:
            log.warning("LLM returned empty fields — using baseline analysis")
            return None

        usage = completion.usage
        tokens = {
            "prompt": getattr(usage, "prompt_tokens", 0) or 0,
            "completion": getattr(usage, "completion_tokens", 0) or 0,
            "total": getattr(usage, "total_tokens", 0) or 0,
            "embedding": 0,
        }
        return analysis, tokens
    except Exception as exc:  # noqa: BLE001 — never fail the run on LLM trouble
        log.warning("Groq reasoning failed (%s) — using baseline analysis", exc)
        return None


@_traced("analyze")
def analyze_node(state: AgentState) -> AgentState:
    anomaly = state["anomaly"]
    sensor = state.get("sensor", {})
    knowledge = state.get("knowledge", [])
    readings = state.get("readings", [])
    staff_candidates = state.get("staff_candidates", [])

    analysis = _baseline_analysis(anomaly, sensor, knowledge)
    tokens = {"prompt": 0, "completion": 0, "total": 0, "embedding": 0}

    reasoned = _llm_reason(anomaly, sensor, readings, knowledge)
    if reasoned is not None:
        analysis, tokens = reasoned

    analysis["similar_cases"] = _compact_knowledge(knowledge)
    analysis["recommended_employee_id"] = (
        staff_candidates[0].get("employee_id") if staff_candidates else None
    )
    analysis["agent_run_id"] = state.get("run_id")

    log.info("analysis generated (llm=%s)", reasoned is not None)
    return {**state, "analysis": analysis, "tokens_used": tokens}


@_traced("patch_anomaly")
def patch_anomaly_node(state: AgentState) -> AgentState:
    anomaly_id = state["anomaly_id"]
    analysis = state["analysis"]
    patch_body = {
        "description": analysis["description"],
        "recommended_solution": analysis["recommended_solution"],
        "similar_cases": analysis.get("similar_cases", []),
        "recommended_employee_id": analysis.get("recommended_employee_id"),
        "agent_run_id": analysis.get("agent_run_id") or state.get("run_id"),
        "status": "analyzed",
    }

    patched = _client(state).patch(f"/anomalies/{anomaly_id}", patch_body)

    log.info("patched anomaly %s as analyzed", anomaly_id)
    return {**state, "patched_anomaly": patched, "final_action": "analyzed"}


def finalize_node(state: AgentState) -> AgentState:
    """Ship the run trace to /agent_logs. Not traced (it is the trace writer)."""
    _post_log(
        state,
        status="completed",
        execution_steps=state.get("steps", []),
        tokens_used=state.get("tokens_used", {"prompt": 0, "completion": 0, "total": 0, "embedding": 0}),
        final_action_taken=state.get("final_action", "unknown"),
    )
    return state


graph = StateGraph(AgentState)

graph.add_node("start", start_node)
graph.add_node("fetch_anomaly", fetch_anomaly_node)
graph.add_node("skip", skip_node)
graph.add_node("fetch_sensor", fetch_sensor_node)
graph.add_node("fetch_readings", fetch_readings_node)
graph.add_node("search_knowledge", search_knowledge_node)
graph.add_node("find_staff", find_staff_node)
graph.add_node("analyze", analyze_node)
graph.add_node("patch_anomaly", patch_anomaly_node)
graph.add_node("finalize", finalize_node)

graph.set_entry_point("start")
graph.add_edge("start", "fetch_anomaly")
graph.add_conditional_edges(
    "fetch_anomaly",
    route_status,
    {
        "process": "fetch_sensor",
        "skip": "skip",
    },
)
graph.add_edge("skip", "finalize")
graph.add_edge("fetch_sensor", "fetch_readings")
graph.add_edge("fetch_readings", "search_knowledge")
graph.add_edge("search_knowledge", "find_staff")
graph.add_edge("find_staff", "analyze")
graph.add_edge("analyze", "patch_anomaly")
graph.add_edge("patch_anomaly", "finalize")
graph.add_edge("finalize", END)

app = graph.compile()


def run_anomaly_graph(
    fields: Mapping[str, str] | str,
    *,
    base_url: str | None = None,
) -> AgentState:
    """Run the graph from a Redis job fields dict or a direct anomaly id."""

    if isinstance(fields, str):
        state: AgentState = {"anomaly_id": fields}
    else:
        state = {
            "job_fields": dict(fields),
            "anomaly_id": fields.get("anomaly_id", ""),
        }
    state["run_id"] = f"agent-run-{uuid.uuid4()}"
    state["steps"] = []
    if base_url:
        state["base_url"] = base_url
    return app.invoke(state)


def process_anomaly_job(fields: Mapping[str, str]) -> None:
    """Drop-in callable for agent_worker.consumer.process_anomaly_job."""

    run_anomaly_graph(fields)
