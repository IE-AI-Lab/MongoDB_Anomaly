"""
FastAPI application factory / entrypoint.

Run with: `uvicorn ingestor_service.app:app`

This service is deliberately minimal:
- validate payload
- store telemetry in Mongo
- run in-memory anomaly detection
- dispatch anomaly jobs (stub or Redis stream) if triggered

The HTTP surface lives in the `api/` package; `app.py` only wires it together.
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from .api import all_routers
from .core.db import ensure_indexes
from .messaging.queue import ensure_anomaly_stream


load_dotenv()

app = FastAPI(title="Telemetry Ingestor", version="0.1.0")

for _router in all_routers:
    app.include_router(_router)


@app.on_event("startup")
def _startup() -> None:
    """
    Startup hook.

    - Ensures DB connection is healthy (ping happens in db.get_client()).
    - Ensures indexes exist (including TTL).
    """
    ensure_indexes()
    ensure_anomaly_stream()
