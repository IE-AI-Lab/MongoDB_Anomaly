from __future__ import annotations

from typing import Any, Optional

import requests
from langchain_core.tools import tool

from . import config


def _base_url() -> str:
    return config.data_layer_base_url()


def _get(path: str, **params: Any) -> Any:
    response = requests.get(
        f"{_base_url()}{path}",
        params={k: v for k, v in params.items() if v is not None},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


@tool
def query_rag_knowledge_base(
    query: str,
    equipment_type: Optional[str] = None,
    error_codes: Optional[str] = None,
    k: int = 5,
) -> dict[str, Any]:
    """
    Search the backend RAG knowledge endpoint.

    The agent writes the natural-language query and can optionally filter by
    equipment_type and comma-separated error_codes from the anomaly context.
    """
    try:
        results = _get(
            "/knowledge/search",
            q=query,
            equipment_type=equipment_type,
            error_codes=error_codes,
            k=k,
        )
    except requests.RequestException as exc:
        return {"error": str(exc), "query_used": query, "results": []}

    return {
        "query_used": query,
        "results": results,
    }


@tool
def get_staff_contact(
    severity: str,
    sensor_id: Optional[str] = None,
    specialization: Optional[str] = None,
    facility_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Call the backend staff endpoint for on-call candidates.

    The agent should pass specialization from the anomaly metric type when it is
    known. If only sensor_id is available, this tool tries to infer it from the
    backend sensor record.
    """
    sensor: dict[str, Any] = {}
    if sensor_id:
        try:
            sensor = _get(f"/sensors/{sensor_id}")
        except requests.RequestException:
            pass

    specialization = specialization or sensor.get("metric_type")
    facility_id = facility_id or sensor.get("facility_id")
    try:
        staff = _get(
            "/staff_on_call",
            is_on_call="true",
            specialization=specialization,
            handled_severity_type=severity,
            facility_id=sensor.get("facility_id"),
        )
    except requests.RequestException as exc:
        return {
            "error": str(exc),
            "sensor_id": sensor_id,
            "severity": severity,
            "specialization": specialization,
            "facility_id": facility_id,
            "staff_candidates": [],
        }

    return {
        "sensor_id": sensor_id,
        "severity": severity,
        "specialization": specialization,
        "facility_id": facility_id,
        "staff_candidates": staff,
    }


@tool
def retrieve_recent_alerts(sensor_id: str) -> dict[str, Any]:
    """
    Retrieve recent anomaly records for this sensor from the backend API.
    """
    try:
        anomalies = _get("/anomalies", sensor_id=sensor_id, limit=5)
    except requests.RequestException as exc:
        return {"error": str(exc), "sensor_id": sensor_id, "recent_alerts": []}

    return {
        "sensor_id": sensor_id,
        "recent_alerts": anomalies,
    }


@tool
def retrieve_machine_memory(sensor_id: str) -> dict[str, Any]:
    """
    Retrieve backend context that replaces the old direct Mongo machine memory lookup.
    """
    try:
        sensor = _get(f"/sensors/{sensor_id}")
        readings = _get(f"/sensors/{sensor_id}/readings", minutes=60, limit=20)
        anomalies = _get("/anomalies", sensor_id=sensor_id, limit=5)
    except requests.RequestException as exc:
        return {"error": str(exc), "sensor_id": sensor_id, "memory": None}

    return {
        "sensor_id": sensor_id,
        "memory": {
            "sensor": sensor,
            "recent_readings": readings,
            "recent_anomalies": anomalies,
        },
    }
