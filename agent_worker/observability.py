"""OpenTelemetry setup + metrics helpers for agent worker (env-gated)."""

from __future__ import annotations

import logging
from typing import Any

from . import config

log = logging.getLogger(__name__)

_otel_ready = False
_jobs_counter: Any = None
_job_duration_hist: Any = None


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


def setup_worker_observability() -> None:
    _configure_otel()


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
