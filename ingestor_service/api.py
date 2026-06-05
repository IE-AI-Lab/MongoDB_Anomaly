"""
FastAPI entrypoint for telemetry ingestion.

This service is deliberately minimal:
- validate payload
- store telemetry in Mongo
- run in-memory anomaly detection
- dispatch anomaly jobs (stub or Redis stream) if triggered
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from .db import ensure_indexes
from .ingest import persist_telemetry
from .models import IngestResponse, TelemetryIngestEvent
from .detector.detect import process_telemetry
from .queue import ensure_anomaly_stream
from .routes_read import router as read_router
from .routes_write import router as write_router


load_dotenv()

app = FastAPI(title="Telemetry Ingestor", version="0.1.0")
app.include_router(read_router)
app.include_router(write_router)


@app.on_event("startup")
def _startup() -> None:
    """
    Startup hook.

    - Ensures DB connection is healthy (ping happens in db.get_client()).
    - Ensures indexes exist (including TTL).
    """
    ensure_indexes()
    ensure_anomaly_stream()


@app.get("/health")
def health() -> dict[str, str]:
    """Basic health check for load balancers and local debugging."""
    return {"status": "ok"}


@app.post("/ingest/telemetry", response_model=IngestResponse)
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

