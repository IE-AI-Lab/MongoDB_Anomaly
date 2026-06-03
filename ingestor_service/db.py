"""
MongoDB connection and index management for the ingestor service.

This uses synchronous PyMongo for simplicity. For high concurrency you'd typically:
- switch FastAPI endpoints to async + Motor, or
- keep PyMongo but run blocking IO in a threadpool.
"""

from __future__ import annotations

from typing import Any

import certifi
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from . import config


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

    # telemetry retention: keep 7 days
    ttl_seconds = 60 * 60 * 24 * config.telemetry_ttl_days()
    # Time-series TTL requires a partialFilterExpression on the metaField (sensor_id).
    db["telemetry_history"].create_index(
        [("timestamp_utc", ASCENDING)],
        expireAfterSeconds=ttl_seconds,
        partialFilterExpression={"sensor_id": {"$exists": True}},
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
    db["knowledge_base"].create_index([("source_type", ASCENDING)])

    db["sensors"].create_index([("sensor_id", ASCENDING)], unique=True)
    db["sensors"].create_index([("is_active", ASCENDING), ("metric_type", ASCENDING)])

    db["session_events"].create_index([("session_id", ASCENDING), ("ts", DESCENDING)])

