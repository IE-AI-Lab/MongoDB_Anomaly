"""Redis Streams consumer loop for anomaly jobs."""

from __future__ import annotations

import logging
import signal
import time
from typing import Any

import redis
import requests

from . import config

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
    try:
        r.xgroup_create(
            name=config.anomaly_stream_key(),
            groupname=config.anomaly_consumer_group(),
            id="0",
            mkstream=True,
        )
        log.info("created consumer group %s", config.anomaly_consumer_group())
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def process_anomaly_job(fields: dict[str, str]) -> None:
    """
    Handle one queued anomaly.

    Today: fetch context from the ingestor read API and log a summary.
    Replace/extend this with your LangGraph graph invocation.
    """
    anomaly_id = fields.get("anomaly_id", "")
    base = config.data_layer_base_url()
    url = f"{base}/anomalies/{anomaly_id}"

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    anomaly = resp.json()

    log.info(
        "processing anomaly_id=%s sensor_id=%s error_code=%s severity=%s:%s status=%s",
        anomaly.get("anomaly_id"),
        anomaly.get("sensor_id"),
        anomaly.get("error_code"),
        anomaly.get("severity_type"),
        anomaly.get("severity_level"),
        anomaly.get("status"),
    )


def run_consumer() -> None:
    """Block on Redis and process jobs until interrupted."""
    global _running
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    r = _make_redis()
    ensure_consumer_group(r)

    stream = config.anomaly_stream_key()
    group = config.anomaly_consumer_group()
    consumer = config.consumer_name()
    block_ms = config.consumer_block_ms()

    log.info(
        "agent worker listening stream=%s group=%s consumer=%s block_ms=%s",
        stream,
        group,
        consumer,
        block_ms,
    )

    while _running:
        try:
            batches = r.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=1,
                block=block_ms,
            )
        except redis.TimeoutError:
            # Normal when BLOCK expires with no new jobs — keep listening.
            continue
        except redis.ConnectionError as exc:
            log.warning("redis connection error: %s — retrying in 2s", exc)
            time.sleep(2)
            continue

        if not batches:
            continue

        for _stream_name, messages in batches:
            for message_id, fields in messages:
                try:
                    process_anomaly_job(fields)
                    r.xack(stream, group, message_id)
                    log.info("acked message_id=%s anomaly_id=%s", message_id, fields.get("anomaly_id"))
                except Exception:
                    log.exception(
                        "job failed message_id=%s anomaly_id=%s — left pending for retry",
                        message_id,
                        fields.get("anomaly_id"),
                    )

    log.info("agent worker stopped")
