"""Redis Streams dispatch for newly detected anomalies.

When AGENT_DISPATCH=redis, each anomaly is appended to a stream after Mongo
persistence. A separate agent_worker process consumes jobs via XREADGROUP.

The ingestor never blocks on agent execution — only on a fast XADD.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from . import config
from .agent_stub import handle_anomaly

log = logging.getLogger(__name__)

_redis_client: Any | None = None


def _redis():
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.Redis.from_url(
            config.redis_url(),
            decode_responses=True,
            socket_connect_timeout=5,
        )
    return _redis_client


def ensure_anomaly_stream() -> None:
    """Create the stream and consumer group if they do not exist yet."""
    if config.agent_dispatch() != "redis":
        return

    import redis

    r = _redis()
    try:
        r.xgroup_create(
            name=config.anomaly_stream_key(),
            groupname=config.anomaly_consumer_group(),
            id="0",
            mkstream=True,
        )
        log.info(
            "created stream %s with group %s",
            config.anomaly_stream_key(),
            config.anomaly_consumer_group(),
        )
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _stream_fields(anomaly_doc: dict[str, Any]) -> dict[str, str]:
    ts = anomaly_doc.get("timestamp_utc")
    if isinstance(ts, datetime):
        ts_str = ts.isoformat()
    else:
        ts_str = str(ts or "")

    return {
        "anomaly_id": str(anomaly_doc.get("anomaly_id", "")),
        "sensor_id": str(anomaly_doc.get("sensor_id", "")),
        "error_code": str(anomaly_doc.get("error_code", "")),
        "severity_type": str(anomaly_doc.get("severity_type", "")),
        "severity_level": str(anomaly_doc.get("severity_level", "")),
        "timestamp_utc": ts_str,
        "event_type": "anomaly_detected",
    }


def publish_anomaly_job(anomaly_doc: dict[str, Any]) -> Optional[str]:
    """
    Append one anomaly job to the Redis stream.

    Returns the Redis message id on success, or None if publish failed.
    Failures are logged but do not propagate — the anomaly is already in Mongo.
    """
    anomaly_id = anomaly_doc.get("anomaly_id")
    try:
        message_id = _redis().xadd(
            name=config.anomaly_stream_key(),
            fields=_stream_fields(anomaly_doc),
            maxlen=config.anomaly_stream_maxlen(),
            approximate=True,
        )
        log.info("queued anomaly job anomaly_id=%s message_id=%s", anomaly_id, message_id)
        return message_id
    except Exception as exc:
        log.warning(
            "failed to queue anomaly job anomaly_id=%s: %s",
            anomaly_id,
            exc,
        )
        return None


def dispatch_anomaly(anomaly_doc: dict[str, Any]) -> None:
    """Route a new anomaly to the configured agent integration (stub or redis)."""
    mode = config.agent_dispatch()
    if mode == "stub":
        handle_anomaly(anomaly_doc)
        return
    if mode == "redis":
        publish_anomaly_job(anomaly_doc)
        return
    raise RuntimeError(
        f"invalid AGENT_DISPATCH={mode!r}; expected 'stub' or 'redis'"
    )
