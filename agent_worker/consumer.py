"""Redis Streams consumer loop for anomaly jobs.

The worker drains per-severity streams in priority order (high → medium → low)
so urgent anomalies are handled first. A failed job is retried by re-queuing it
to its source stream with an incremented attempt count; once it exhausts
ANOMALY_MAX_RETRIES it is routed to the dead-letter stream ({prefix}:dlq).
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any

import redis

from . import config
from .anomaly_graph import run_anomaly_graph
from .observability import record_job_processed

log = logging.getLogger(__name__)

_running = True


def _handle_stop(signum: int, _frame: Any) -> None:
    global _running
    log.info("received signal %s — shutting down after current job", signum)
    _running = False


def _make_redis() -> redis.Redis:
    block_ms = config.consumer_block_ms()
    # XREADGROUP BLOCK must outlive the block window or redis-py raises TimeoutError.
    socket_timeout = None if block_ms <= 0 else (block_ms / 1000) + 10
    return redis.Redis.from_url(
        config.redis_url(),
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=socket_timeout,
    )


def ensure_consumer_group(r: redis.Redis) -> None:
    """Create the shared consumer group on every priority stream."""
    group = config.anomaly_consumer_group()
    for stream in config.anomaly_priority_streams():
        try:
            r.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
            log.info("created consumer group %s on %s", group, stream)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise


def process_anomaly_job(fields: dict[str, str]) -> None:
    """
    Handle one queued anomaly.

    Fetch context and commit analysis through the LangGraph graph. The graph
    talks to the data layer over HTTP so this worker stays decoupled from Mongo.
    """
    anomaly_id = fields.get("anomaly_id", "")
    log.info("processing anomaly_id=%s via LangGraph", anomaly_id)

    result = run_anomaly_graph(fields, base_url=config.data_layer_base_url())
    if result.get("skipped"):
        log.info("skipped anomaly_id=%s reason=%s", anomaly_id, result.get("skip_reason"))
        return

    patched = result.get("patched_anomaly", {})
    log.info(
        "analyzed anomaly_id=%s status=%s recommended_employee_id=%s",
        patched.get("anomaly_id", anomaly_id),
        patched.get("status"),
        patched.get("recommended_employee_id"),
    )


def _handle_failure(
    r: redis.Redis,
    source_stream: str,
    group: str,
    message_id: str,
    fields: dict[str, str],
) -> None:
    """Retry a failed job or send it to the DLQ once retries are exhausted.

    The replacement message is XADDed *before* the original is acked, so a crash
    mid-handoff yields a harmless duplicate rather than a lost job.
    """
    attempts = int(fields.get("attempts", "0")) + 1
    new_fields = {**fields, "attempts": str(attempts)}
    maxlen = config.anomaly_stream_maxlen()
    anomaly_id = fields.get("anomaly_id", "")

    if attempts >= config.anomaly_max_retries():
        new_fields["failed_at_utc"] = datetime.now(timezone.utc).isoformat()
        new_fields["source_stream"] = source_stream
        dlq = config.anomaly_dlq_stream()
        r.xadd(name=dlq, fields=new_fields, maxlen=maxlen, approximate=True)
        log.error(
            "anomaly_id=%s exhausted %s attempts — moved to DLQ %s",
            anomaly_id,
            attempts,
            dlq,
        )
    else:
        r.xadd(name=source_stream, fields=new_fields, maxlen=maxlen, approximate=True)
        log.warning(
            "anomaly_id=%s failed (attempt %s) — requeued to %s",
            anomaly_id,
            attempts,
            source_stream,
        )

    r.xack(source_stream, group, message_id)


def _process_one(
    r: redis.Redis,
    group: str,
    stream: str,
    message_id: str,
    fields: dict[str, str],
) -> None:
    started = time.perf_counter()
    try:
        process_anomaly_job(fields)
        record_job_processed("success", time.perf_counter() - started)
        r.xack(stream, group, message_id)
        log.info(
            "acked message_id=%s anomaly_id=%s stream=%s",
            message_id,
            fields.get("anomaly_id"),
            stream,
        )
    except Exception:
        record_job_processed("failure", time.perf_counter() - started)
        log.exception(
            "job failed message_id=%s anomaly_id=%s stream=%s",
            message_id,
            fields.get("anomaly_id"),
            stream,
        )
        try:
            _handle_failure(r, stream, group, message_id, fields)
        except Exception:  # noqa: BLE001 — never let retry bookkeeping kill the loop
            log.exception("failed to requeue/DLQ message_id=%s", message_id)


def _next_batch(
    r: redis.Redis, group: str, consumer: str, block_ms: int
) -> list[tuple[str, str, dict[str, str]]]:
    """Return the next jobs to process as (stream, message_id, fields).

    First scans the priority streams non-blocking (high → low) and returns as
    soon as one has work. If everything is idle, issues a single blocking read
    across all streams so the worker doesn't busy-spin.
    """
    priority = config.anomaly_priority_streams()
    rank = {stream: i for i, stream in enumerate(priority)}

    # 1) Non-blocking priority scan.
    for stream in priority:
        try:
            batches = r.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=1,
                block=None,
            )
        except redis.ConnectionError as exc:
            log.warning("redis connection error: %s — retrying in 2s", exc)
            time.sleep(2)
            return []
        items = [(stream, mid, fields) for _s, msgs in (batches or []) for mid, fields in msgs]
        if items:
            return items

    # 2) Idle — block across all priority streams at once.
    try:
        batches = r.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">" for stream in priority},
            count=1,
            block=block_ms,
        )
    except redis.TimeoutError:
        return []
    except redis.ConnectionError as exc:
        log.warning("redis connection error: %s — retrying in 2s", exc)
        time.sleep(2)
        return []

    items = [(s, mid, fields) for s, msgs in (batches or []) for mid, fields in msgs]
    items.sort(key=lambda item: rank.get(item[0], len(priority)))
    return items


def run_consumer() -> None:
    """Block on Redis and process jobs until interrupted."""
    global _running
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    r = _make_redis()
    ensure_consumer_group(r)

    group = config.anomaly_consumer_group()
    consumer = config.consumer_name()
    block_ms = config.consumer_block_ms()

    log.info(
        "agent worker listening streams=%s group=%s consumer=%s block_ms=%s",
        config.anomaly_priority_streams(),
        group,
        consumer,
        block_ms,
    )

    while _running:
        for stream, message_id, fields in _next_batch(r, group, consumer, block_ms):
            _process_one(r, group, stream, message_id, fields)
            if not _running:
                break

    log.info("agent worker stopped")