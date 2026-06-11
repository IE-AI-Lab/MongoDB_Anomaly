"""Telemetry ingestion + health endpoints.

Sync PyMongo variant. Endpoints are plain `def` (FastAPI threadpools blocking
IO). Registered via api/__init__.py's all_routers.

This is the simulator → ingestor entrypoint: validate payload, persist
telemetry, run in-memory anomaly detection, dispatch a job if one is created.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..services.ingest import persist_telemetry
from ..detector.detect import process_telemetry
from ..models import IngestResponse, TelemetryIngestEvent

router = APIRouter(tags=["telemetry"])


@router.get("/health")
def health() -> dict[str, str]:
    """Basic health check for load balancers and local debugging."""
    return {"status": "ok"}


@router.post("/ingest/telemetry", response_model=IngestResponse)
def ingest_telemetry(event: TelemetryIngestEvent) -> IngestResponse:
    """
    Ingest one telemetry event.

    Steps:
    1) Persist telemetry to time-series collection.
    2) Run anomaly detection on the stored document.
    3) If anomaly is created, return its anomaly_id.
    """
    doc = persist_telemetry(event)
    anomaly_doc = process_telemetry(doc)
    if anomaly_doc:
        return IngestResponse(stored=True, anomaly_created=True, anomaly_id=anomaly_doc["anomaly_id"])
    return IngestResponse(stored=True, anomaly_created=False)
