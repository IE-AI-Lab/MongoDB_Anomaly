from __future__ import annotations

import os
import uuid
from typing import Any, Mapping, TypedDict

import requests
from langgraph.graph import END, StateGraph


DEFAULT_BASE_URL = "http://localhost:8000"


class AgentState(TypedDict, total=False):
    anomaly_id: str
    base_url: str
    job_fields: dict[str, str]
    anomaly: dict[str, Any]
    sensor: dict[str, Any]
    readings: list[dict[str, Any]]
    agent_decision: dict[str, Any]
    analysis: dict[str, Any]
    patched_anomaly: dict[str, Any]
    skipped: bool
    skip_reason: str


class DataLayerClient:
    """Small HTTP wrapper around the documented ingestor API."""

    def __init__(self, base_url: str | None = None, timeout_seconds: float = 30.0):
        self.base_url = (base_url or os.getenv("DATA_LAYER_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params)

    def patch(self, path: str, body: Mapping[str, Any]) -> Any:
        return self._request("PATCH", path, json=body)

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


def investigation_agent_node(state: AgentState) -> AgentState:
    from .investigation_agent import run_investigation_agent

    decision = run_investigation_agent(
        state["anomaly"],
        state.get("sensor", {}),
        state.get("readings", []),
    )

    print(f"Agent decision: {decision.get('decision')}")
    print(f"Severity: {decision.get('severity')}")
    print(f"Confidence: {decision.get('confidence')}")

    return {**state, "agent_decision": decision}


def _client(state: AgentState) -> DataLayerClient:
    return DataLayerClient(state.get("base_url"))


def _anomaly_id_from(state: AgentState) -> str:
    anomaly_id = state.get("anomaly_id") or state.get("job_fields", {}).get("anomaly_id", "")
    if not anomaly_id:
        raise ValueError("anomaly_id is required to run the anomaly graph")
    return anomaly_id


def fetch_anomaly_node(state: AgentState) -> AgentState:
    anomaly_id = _anomaly_id_from(state)
    anomaly = _client(state).get(f"/anomalies/{anomaly_id}")

    print(f"Fetched anomaly {anomaly_id} with status={anomaly.get('status')}")
    return {**state, "anomaly_id": anomaly_id, "anomaly": anomaly}


def route_status(state: AgentState) -> str:
    status = state["anomaly"].get("status", "unresolved")
    return "process" if status == "unresolved" else "skip"


def skip_node(state: AgentState) -> AgentState:
    anomaly_id = state["anomaly"].get("anomaly_id", state.get("anomaly_id", ""))
    status = state["anomaly"].get("status", "unknown")
    reason = f"Anomaly {anomaly_id} is already {status}; skipping idempotently."

    print(reason)
    return {**state, "skipped": True, "skip_reason": reason}


def fetch_sensor_node(state: AgentState) -> AgentState:
    sensor_id = state["anomaly"]["sensor_id"]
    sensor = _client(state).get(f"/sensors/{sensor_id}")

    print(f"Fetched sensor {sensor_id}")
    return {**state, "sensor": sensor}


def fetch_readings_node(state: AgentState) -> AgentState:
    sensor_id = state["anomaly"]["sensor_id"]
    readings = _client(state).get(
        f"/sensors/{sensor_id}/readings",
        minutes=60,
        limit=200,
    )

    print(f"Fetched {len(readings)} recent readings for {sensor_id}")
    return {**state, "readings": readings}


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

    description = (
        f"{error_code} detected on {equipment_id}. "
        f"{metric} is {observed}{unit} against limit {limit}{unit} after "
        f"{consecutive_count} consecutive readings. "
        f"Severity is {severity_type} at level {severity_level}."
    )

    recommended_solution = (
        f"Inspect {equipment_id} for the {error_code.lower()} condition, compare the last hour "
        "of telemetry against the retrieved knowledge cases, and schedule corrective maintenance "
        "with the recommended on-call specialist."
    )

    return {
        "description": description,
        "recommended_solution": recommended_solution,
        "recommended_employee_id": None,
        "similar_cases": [],
    }


def analyze_node(state: AgentState) -> AgentState:
    anomaly = state["anomaly"]
    decision = state.get("agent_decision", {})
    fallback = _fallback_analysis(anomaly)

    analysis = {
        "description": decision.get("description") or decision.get("reasoning") or fallback["description"],
        "recommended_solution": (
            decision.get("recommended_solution")
            or decision.get("recommended_action")
            or fallback["recommended_solution"]
        ),
        "similar_cases": decision.get("similar_cases") or fallback["similar_cases"],
        "recommended_employee_id": (
            decision.get("recommended_employee_id")
            or fallback["recommended_employee_id"]
        ),
    }

    print("Analysis generated")
    return {**state, "analysis": analysis}


def patch_anomaly_node(state: AgentState) -> AgentState:
    anomaly_id = state["anomaly_id"]
    analysis = state["analysis"]
    patch_body = {
        "description": analysis["description"],
        "recommended_solution": analysis["recommended_solution"],
        "similar_cases": analysis.get("similar_cases", []),
        "recommended_employee_id": analysis.get("recommended_employee_id"),
        "agent_run_id": analysis.get("agent_run_id") or f"agent-run-{uuid.uuid4()}",
        "status": "analyzed",
    }

    patched = _client(state).patch(f"/anomalies/{anomaly_id}", patch_body)

    print(f"Patched anomaly {anomaly_id} as analyzed")
    return {**state, "patched_anomaly": patched}


graph = StateGraph(AgentState)

graph.add_node("fetch_anomaly", fetch_anomaly_node)
graph.add_node("skip", skip_node)
graph.add_node("fetch_sensor", fetch_sensor_node)
graph.add_node("fetch_readings", fetch_readings_node)
graph.add_node("investigation_agent", investigation_agent_node)
graph.add_node("analyze", analyze_node)
graph.add_node("patch_anomaly", patch_anomaly_node)

graph.set_entry_point("fetch_anomaly")
graph.add_conditional_edges(
    "fetch_anomaly",
    route_status,
    {
        "process": "fetch_sensor",
        "skip": "skip",
    },
)
graph.add_edge("skip", END)
graph.add_edge("fetch_sensor", "fetch_readings")
graph.add_edge("fetch_readings", "investigation_agent")
graph.add_edge("investigation_agent", "analyze")
graph.add_edge("analyze", "patch_anomaly")
graph.add_edge("patch_anomaly", END)

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
    if base_url:
        state["base_url"] = base_url
    return app.invoke(state)


def process_anomaly_job(fields: Mapping[str, str]) -> None:
    """Drop-in callable for agent_worker.consumer.process_anomaly_job."""

    run_anomaly_graph(fields)
