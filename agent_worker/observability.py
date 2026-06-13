"""Agent-worker observability: LangSmith tracing + optional OpenTelemetry (env-gated)."""

from __future__ import annotations

import logging
import os
from typing import Any

from . import config

log = logging.getLogger(__name__)

_otel_ready = False
_jobs_counter: Any = None
_job_duration_hist: Any = None
_queue_gauges_registered = False
_redis_client: Any = None


def init_langsmith() -> None:
    """
    Configure LangSmith tracing from env vars.

    LangChain/LangGraph automatically emit traces when LANGCHAIN_TRACING_V2=true
    and LANGCHAIN_API_KEY is set. We keep this helper tiny and non-fatal.
    """
    if not os.getenv("LANGCHAIN_API_KEY"):
        log.info("LangSmith tracing disabled (LANGCHAIN_API_KEY not set)")
        return

    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    project = os.environ.setdefault("LANGCHAIN_PROJECT", "mongodb-anomaly-agent")
    log.info("LangSmith tracing enabled project=%s", project)


def _configure_otel() -> bool:
    global _otel_ready
    if _otel_ready:
        return True
    if not config.otel_enabled():
        return False

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("OTEL_ENABLED=true but OpenTelemetry packages are not installed")
        return False

    endpoint = config.otel_exporter_otlp_endpoint()
    resource = Resource.create({"service.name": config.otel_service_name("agent_worker")})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True)
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

    _otel_ready = True
    log.info("OpenTelemetry enabled endpoint=%s service=%s", endpoint, config.otel_service_name("agent_worker"))
    return True


def _get_redis_client() -> Any:
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.Redis.from_url(
            config.redis_url(),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def _observe_stream_length(_options: Any):
    from opentelemetry.metrics import Observation

    stream = config.anomaly_stream_key()
    try:
        length = _get_redis_client().xlen(stream)
    except Exception:  # noqa: BLE001 — metrics must never break the worker
        return []
    return [Observation(length, {"stream": stream})]


def _observe_stream_pending(_options: Any):
    from opentelemetry.metrics import Observation

    stream = config.anomaly_stream_key()
    group = config.anomaly_consumer_group()
    try:
        info = _get_redis_client().xpending(stream, group)
        pending = info.get("pending", 0) if isinstance(info, dict) else 0
    except Exception:  # noqa: BLE001 — group may not exist yet / redis down
        return []
    return [Observation(pending, {"stream": stream, "group": group})]


def _register_queue_gauges() -> None:
    global _queue_gauges_registered
    if _queue_gauges_registered:
        return

    from opentelemetry import metrics

    meter = metrics.get_meter("agent_worker.queue")
    meter.create_observable_gauge(
        "anomaly_stream_length",
        callbacks=[_observe_stream_length],
        description="Total entries in the anomaly Redis stream",
        unit="1",
    )
    meter.create_observable_gauge(
        "anomaly_stream_pending",
        callbacks=[_observe_stream_pending],
        description="Unacknowledged (pending) jobs for the consumer group",
        unit="1",
    )
    _queue_gauges_registered = True


def setup_worker_observability() -> None:
    if _configure_otel():
        _register_queue_gauges()


def record_job_processed(result: str, duration_seconds: float) -> None:
    global _jobs_counter
    global _job_duration_hist

    if not _configure_otel():
        return

    if _jobs_counter is None or _job_duration_hist is None:
        from opentelemetry import metrics

        meter = metrics.get_meter("agent_worker.consumer")
        _jobs_counter = meter.create_counter(
            "agent_jobs_processed_total",
            description="Number of anomaly jobs processed by the agent worker",
            unit="1",
        )
        _job_duration_hist = meter.create_histogram(
            "agent_job_duration_seconds",
            description="Duration of a single anomaly job",
            unit="s",
        )

    safe_result = result if result in {"success", "failure"} else "unknown"
    _jobs_counter.add(1, attributes={"result": safe_result})
    _job_duration_hist.record(duration_seconds, attributes={"result": safe_result})
