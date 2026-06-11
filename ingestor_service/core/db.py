"""
MongoDB connection and index management for the ingestor service.

This uses synchronous PyMongo for simplicity. For high concurrency you'd typically:
- switch FastAPI endpoints to async + Motor, or
- keep PyMongo but run blocking IO in a threadpool.
"""

from __future__ import annotations

import logging
from typing import Any

import certifi
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import OperationFailure

from . import config

log = logging.getLogger(__name__)


_client: MongoClient[dict[str, Any]] | None = None


def get_client() -> MongoClient[dict[str, Any]]:
    """
    Return a singleton MongoDB client.

    Why singleton:
    - PyMongo maintains an internal connection pool.
    - Creating a new client per request is expensive and can exhaust sockets.
    """
    global _client
    if _client is None:
        _client = MongoClient(
            config.mongo_uri(),
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=10_000,
        )
        _client.admin.command("ping")
    return _client


def get_db() -> Database[dict[str, Any]]:
    """Return the configured MongoDB database handle."""
    return get_client()[config.db_name()]


def col(name: str) -> Collection[dict[str, Any]]:
    """Convenience accessor for a named collection."""
    return get_db()[name]


def ensure_indexes() -> None:
    """
    Ensure required indexes exist.

    This is safe to run on every process startup. If an index exists already,
    MongoDB treats create_index as a no-op (same definition).
    """
    db = get_db()

    # telemetry retention: keep N days. For TIME-SERIES collections, expiry is
    # configured at the collection level via expireAfterSeconds (collMod), NOT
    # via a secondary TTL index on the timeField — the latter is rejected or
    # silently ineffective on most MongoDB/Atlas versions. collMod is idempotent;
    # we guard it so a missing collection (init_db not yet run) doesn't crash
    # startup.
    ttl_seconds = 60 * 60 * 24 * config.telemetry_ttl_days()
    try:
        db.command("collMod", "telemetry_history", expireAfterSeconds=ttl_seconds)
    except OperationFailure as exc:
        log.warning(
            "could not set telemetry_history TTL (run python -m scripts.init_db first?): %s", exc
        )

    db["anomalies"].create_index([("anomaly_id", ASCENDING)], unique=True)
    db["anomalies"].create_index(
        [
            ("status", ASCENDING),
            ("severity_type", ASCENDING),
            ("severity_level", DESCENDING),
            ("timestamp_utc", DESCENDING),
        ]
    )
    db["anomalies"].create_index([("sensor_id", ASCENDING), ("timestamp_utc", DESCENDING)])

    db["agent_execution_logs"].create_index([("run_id", ASCENDING)], unique=True)
    db["agent_execution_logs"].create_index([("anomaly_id", ASCENDING), ("started_at", DESCENDING)])

    db["system_metadata"].create_index([("config_type", ASCENDING), ("target_metric", ASCENDING)])
    db["staff_on_call"].create_index([("employee_id", ASCENDING)], unique=True)
    db["staff_on_call"].create_index(
        [
            ("is_on_call", ASCENDING),
            ("handled_severity_type", ASCENDING),
            ("specialization", ASCENDING),
            ("escalation_rank", ASCENDING),
        ]
    )

    db["knowledge_base"].create_index([("document_id", ASCENDING)], unique=True)
    # Filters used by rag.search_knowledge's $vectorSearch pre-filter and the
    # recency fallback. (No source_type index — no document carries that field.)
    db["knowledge_base"].create_index([("equipment_type", ASCENDING)])
    db["knowledge_base"].create_index([("associated_error_codes", ASCENDING)])

    db["sensors"].create_index([("sensor_id", ASCENDING)], unique=True)
    db["sensors"].create_index([("is_active", ASCENDING), ("metric_type", ASCENDING)])

    db["session_events"].create_index([("session_id", ASCENDING), ("ts", DESCENDING)])

