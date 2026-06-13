"""OpenTelemetry setup for the ingestor service (env-gated)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from .core import config

log = logging.getLogger(__name__)

_otel_ready = False
_anomaly_counter: Any = None


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
    resource = Resource.create({"service.name": config.otel_service_name("ingestor_service")})

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
    log.info("OpenTelemetry enabled endpoint=%s service=%s", endpoint, config.otel_service_name("ingestor_service"))
    return True


def setup_fastapi_observability(app: FastAPI) -> None:
    if not _configure_otel():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        log.warning("OTEL_ENABLED=true but fastapi instrumentation package is missing")
        return

    FastAPIInstrumentor().instrument_app(app)


def record_anomaly_created(error_code: str, metric_type: str, severity_type: str) -> None:
    global _anomaly_counter
    if not _configure_otel():
        return

    if _anomaly_counter is None:
        from opentelemetry import metrics

        meter = metrics.get_meter("ingestor_service.detector")
        _anomaly_counter = meter.create_counter(
            "anomalies_created_total",
            description="Total anomalies created by detector",
            unit="1",
        )

    _anomaly_counter.add(
        1,
        attributes={
            "error_code": error_code or "unknown",
            "metric_type": metric_type or "unknown",
            "severity_type": severity_type or "unknown",
        },
    )
