"""
Agent stub.

For now, the "agent" is only a function invoked when an anomaly triggers.
This lets you build the full telemetry → anomaly → action pipeline without any
LLM/RAG/staff-notification complexity yet.

Later, this is where you'd integrate:
- knowledge_base retrieval (manual rules + vector search)
- staff_on_call matching and escalation
- action execution (SMS/email/ticket creation)
- agent_execution_logs tracing
"""

from __future__ import annotations

from typing import Any


def handle_anomaly(anomaly_doc: dict[str, Any]) -> None:
    """
    Receive a fully formed anomaly document and perform a placeholder action.

    Current behavior:
    - Print a compact summary to stdout so you can see the pipeline working.

    Expected inputs:
    - The document shape matches the `anomalies` collection contract (at minimum it should
      include anomaly_id, sensor_id, error_code, severity_type, severity_level, trigger_value).
    """
    anomaly_id = anomaly_doc.get("anomaly_id")
    sensor_id = anomaly_doc.get("sensor_id")
    code = anomaly_doc.get("error_code")
    sev_type = anomaly_doc.get("severity_type")
    sev_level = anomaly_doc.get("severity_level")
    trigger = anomaly_doc.get("trigger_value", {})

    observed = trigger.get("observed")
    limit = trigger.get("limit")
    metric = trigger.get("metric")

    print(
        f"[AGENT_STUB] anomaly_id={anomaly_id} sensor_id={sensor_id} "
        f"error_code={code} severity={sev_type}:{sev_level} "
        f"metric={metric} observed={observed} limit={limit}"
    )

