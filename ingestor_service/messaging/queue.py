"""Redis Streams dispatch for newly detected anomalies.

When AGENT_DISPATCH=redis, each anomaly is appended to a stream after Mongo
persistence. A separate agent_worker process consumes jobs via XREADGROUP.

The ingestor never blocks on agent execution — only on a fast XADD.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from ..core import config
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
    """Create the per-severity streams and their consumer group if missing."""
    if config.agent_dispatch() != "redis":
        return

    import redis

    r = _redis()
    group = config.anomaly_consumer_group()
    for stream in config.anomaly_severity_streams().values():
        try:
            r.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
            log.info("created stream %s with group %s", stream, group)
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
        "detection_method": str(anomaly_doc.get("detection_method", "")),
        "timestamp_utc": ts_str,
        "event_type": "anomaly_detected",
        "attempts": "0",
    }


def publish_anomaly_job(anomaly_doc: dict[str, Any]) -> Optional[str]:
    """
    Append one anomaly job to the severity-routed Redis stream.

    The destination stream is chosen from the anomaly's severity_type
    (high/medium/low) so the worker can prioritize. Returns the Redis message id
    on success, or None if publish failed. Failures are logged but do not
    propagate — the anomaly is already in Mongo.
    """
    anomaly_id = anomaly_doc.get("anomaly_id")
    stream = config.anomaly_stream_for_severity(anomaly_doc.get("severity_type", ""))
    try:
        message_id = _redis().xadd(
            name=stream,
            fields=_stream_fields(anomaly_doc),
            maxlen=config.anomaly_stream_maxlen(),
            approximate=True,
        )
        log.info(
            "queued anomaly job anomaly_id=%s stream=%s message_id=%s",
            anomaly_id,
            stream,
            message_id,
        )
        return message_id
    except Exception as exc:
        log.warning(
            "failed to queue anomaly job anomaly_id=%s: %s",
            anomaly_id,
            exc,
        )
        return None


def reset_anomaly_streams() -> dict[str, Any]:
    """
    Wipe all anomaly streams and recreate empty consumer groups.

    Deletes each stream key (clears both XLEN and XPENDING), then calls
    ensure_anomaly_stream() so fresh empty streams exist for the next run.
    Also removes the legacy single-stream key (ANOMALY_STREAM_KEY) if set.
    """
    if config.agent_dispatch() != "redis":
        return {"skipped": True, "reason": "AGENT_DISPATCH is not redis"}

    streams = set(config.anomaly_severity_streams().values())
    streams.add(config.anomaly_dlq_stream())
    legacy = config.anomaly_stream_key()
    if legacy:
        streams.add(legacy)

    r = _redis()
    deleted: dict[str, bool] = {}
    for stream in sorted(streams):
        try:
            deleted[stream] = bool(r.delete(stream))
            log.info("deleted anomaly stream %s", stream)
        except Exception as exc:
            log.warning("failed to delete anomaly stream %s: %s", stream, exc)
            deleted[stream] = False

    ensure_anomaly_stream()
    return {"streams_deleted": deleted, "consumer_groups_recreated": True}


def trim_anomaly_stream() -> bool:
    """
    Drop all jobs from every anomaly stream.

    Delegates to reset_anomaly_streams() for a full wipe (len=0, pending=0).
    Used by POST /simulation/reset and POST /queues/reset.
    """
    result = reset_anomaly_streams()
    if result.get("skipped"):
        return False
    return all(result.get("streams_deleted", {}).values())


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
