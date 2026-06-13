from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Mapping, TypedDict

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
    agent_decision: dict[str, Any]
    analysis: dict[str, Any]
    patched_anomaly: dict[str, Any]
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


def _traced(tool_name: str) -> Callable[[Callable[[AgentState], AgentState]], Callable[[AgentState], AgentState]]:
    def decorate(fn: Callable[[AgentState], AgentState]) -> Callable[[AgentState], AgentState]:
        def wrapper(state: AgentState) -> AgentState:
            steps = list(state.get("steps", []))
            index = len(steps)
            started = time.time()
            result = fn(state)
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
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to write agent_execution_logs run_id=%s: %s", run_id, exc)


def _compact_knowledge(docs: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for doc in docs[:5]:
        # The LLM sometimes returns similar_cases as plain strings instead of
        # the structured knowledge docs — keep those as free-text snippets.
        if isinstance(doc, str):
            compact.append(
                {
                    "document_id": None,
                    "section_title": None,
                    "equipment_type": None,
                    "associated_error_codes": None,
                    "text_content": doc[:800],
                }
            )
            continue
        if not isinstance(doc, dict):
            continue
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


def _fallback_analysis(anomaly: Mapping[str, Any]) -> dict[str, Any]:
    trigger = anomaly.get("trigger_value") or {}
    metric = trigger.get("metric") or anomaly.get("metric_type", "metric")
    observed = trigger.get("observed", "unknown")
    limit = trigger.get("limit", "unknown")
    consecutive_count = trigger.get("consecutive_count", "multiple")
    error_code = anomaly.get("error_code", "ANOMALY")
    severity_type = anomaly.get("severity_type", "unknown")
    severity_level = anomaly.get("severity_level", "unknown")
    equipment_id = anomaly.get("equipment_id") or anomaly.get("sensor_id", "equipment")
    unit = trigger.get("unit") or ""

    return {
        "description": (
            f"{error_code} detected on {equipment_id}. "
            f"{metric} is {observed}{unit} against limit {limit}{unit} after "
            f"{consecutive_count} consecutive readings. "
            f"Severity is {severity_type} at level {severity_level}."
        ),
        "recommended_solution": (
            f"Inspect {equipment_id} for the {error_code.lower()} condition, compare the last hour "
            "of telemetry against retrieved knowledge cases, and schedule corrective maintenance "
            "with the recommended on-call specialist."
        ),
        "recommended_employee_id": None,
        "similar_cases": [],
    }


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
    """Bootstrap with a small telemetry slice — agent tools can fetch more."""
    sensor_id = state["anomaly"]["sensor_id"]
    readings = _client(state).get(
        f"/sensors/{sensor_id}/readings",
        minutes=60,
        limit=10,
    )
    log.info("fetched %s bootstrap readings for %s", len(readings), sensor_id)
    return {**state, "readings": readings}


@_traced("investigation_agent")
def investigation_agent_node(state: AgentState) -> AgentState:
    from .investigation_agent import run_investigation_agent

    decision = run_investigation_agent(
        state["anomaly"],
        state.get("sensor", {}),
        state.get("readings", []),
        run_id=state.get("run_id"),
    )
    log.info(
        "investigation complete decision=%s confidence=%s rag_query=%s",
        decision.get("decision"),
        decision.get("confidence"),
        decision.get("rag_query_used"),
    )
    return {**state, "agent_decision": decision}


@_traced("analyze")
def analyze_node(state: AgentState) -> AgentState:
    anomaly = state["anomaly"]
    decision = state.get("agent_decision", {})
    fallback = _fallback_analysis(anomaly)

    similar = decision.get("similar_cases") or fallback["similar_cases"]
    analysis = {
        "description": decision.get("description") or decision.get("reasoning") or fallback["description"],
        "recommended_solution": (
            decision.get("recommended_solution")
            or decision.get("recommended_action")
            or fallback["recommended_solution"]
        ),
        "similar_cases": _compact_knowledge(similar) if similar else [],
        "recommended_employee_id": (
            decision.get("recommended_employee_id") or fallback["recommended_employee_id"]
        ),
        "agent_run_id": state.get("run_id"),
        "agent_decision": decision.get("decision"),
        "agent_confidence": decision.get("confidence"),
        "agent_reasoning": decision.get("reasoning"),
    }

    log.info("analysis prepared employee=%s", analysis.get("recommended_employee_id"))
    return {
        **state,
        "analysis": analysis,
        "tokens_used": {"prompt": 0, "completion": 0, "total": 0, "embedding": 0},
    }


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
graph.add_node("investigation_agent", investigation_agent_node)
graph.add_node("analyze", analyze_node)
graph.add_node("patch_anomaly", patch_anomaly_node)
graph.add_node("finalize", finalize_node)

graph.set_entry_point("start")
graph.add_edge("start", "fetch_anomaly")
graph.add_conditional_edges(
    "fetch_anomaly",
    route_status,
    {"process": "fetch_sensor", "skip": "skip"},
)
graph.add_edge("skip", "finalize")
graph.add_edge("fetch_sensor", "fetch_readings")
graph.add_edge("fetch_readings", "investigation_agent")
graph.add_edge("investigation_agent", "analyze")
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
