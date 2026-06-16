"""
Configuration for the ingestor/detector service.

This module is intentionally small and boring:
- Load environment variables (via python-dotenv in the process entrypoint if desired).
- Provide typed accessors with safe defaults.

In production you would typically also include:
- Structured logging config
- Feature flags (detect-inline vs background)
- Rate limiting / auth settings for ingestion endpoints
"""

from __future__ import annotations

import os


def require_env(name: str) -> str:
    """
    Return an environment variable value or raise a clear error.

    Why:
    - Failing fast at startup prevents partial deployment with a broken DB connection.
    - Avoids silent None/"" issues later.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def mongo_uri() -> str:
    """MongoDB connection URI (Atlas SRV or standard URI)."""
    return require_env("MONGO_URI")


def db_name() -> str:
    """MongoDB database name to use within the cluster."""
    return require_env("DB_NAME")


def telemetry_ttl_days() -> int:
    """
    How long telemetry is retained in the database.

    Note:
    - TTL is enforced by MongoDB in the background (best-effort).
    - Default is 7 days as per the hybrid recommendation.
    """
    return int(os.getenv("TELEMETRY_TTL_DAYS", "7"))


def service_name() -> str:
    """Used for audit fields like last_updated_by or event source labels."""
    return os.getenv("SERVICE_NAME", "ingestor_service")


# --- Embeddings: managed by Atlas Vector Search (Voyage AI Automated Embedding)
# Atlas generates embeddings at index + query time from `text_content`; this
# service never computes or stores vectors and needs no embeddings API key.
# This model MUST match the model set in the `knowledge_vector` autoEmbed index.


def voyage_embed_model() -> str:
    """Voyage AI model used by the knowledge_vector autoEmbed index + queries."""
    return os.getenv("VOYAGE_EMBED_MODEL", "voyage-4-lite")


# --- Chat / agent reasoning: Groq (OpenAI-compatible endpoint) ----------------
# The agent team points an OpenAI-SDK client at groq_base_url() with
# groq_api_key() to use Groq's free Llama/Mixtral/Gemma models.


def groq_api_key() -> str:
    """Groq API key (OpenAI-compatible). Optional at startup."""
    return os.getenv("GROQ_API_KEY", "")


def groq_base_url() -> str:
    """Groq's OpenAI-compatible base URL."""
    return os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")


def chat_model() -> str:
    """Chat model used by the agent team's reasoning layer."""
    return os.getenv("CHAT_MODEL", "llama-3.3-70b-versatile")


# --- Agent dispatch: stub (stdout) or Redis Streams queue -------------------


def agent_dispatch() -> str:
    """
    How newly detected anomalies are handed off to the agent layer.

    - stub: print via agent_stub (local dev without Redis)
    - redis: XADD to the anomaly stream for agent_worker to consume
    """
    return os.getenv("AGENT_DISPATCH", "stub").strip().lower()


def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def anomaly_stream_key() -> str:
    return os.getenv("ANOMALY_STREAM_KEY", "anomaly:jobs")


def anomaly_consumer_group() -> str:
    return os.getenv("ANOMALY_CONSUMER_GROUP", "agent-workers")


def anomaly_stream_maxlen() -> int:
    return int(os.getenv("ANOMALY_STREAM_MAXLEN", "10000"))


def otel_enabled() -> bool:
    return os.getenv("OTEL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def otel_exporter_otlp_endpoint() -> str:
    return os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")


def otel_service_name(default: str = "ingestor_service") -> str:
    # Empty (OTEL_SERVICE_NAME=) means "unset" — fall back to the per-process
    # default rather than reporting an empty service.name to the collector.
    return os.getenv("OTEL_SERVICE_NAME") or default


# --- Hybrid severity-based Redis routing -------------------------------------
# Anomalies are routed to per-severity streams ({prefix}:high|medium|low) so the
# worker can drain high-severity jobs first. Failed jobs end up in {prefix}:dlq.


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def anomaly_stream_prefix() -> str:
    return os.getenv("ANOMALY_STREAM_PREFIX", "anomaly")


def anomaly_priority_order() -> list[str]:
    """Severity buckets in descending priority."""
    return ["high", "medium", "low"]


def anomaly_severity_streams() -> dict[str, str]:
    """Map each severity bucket to its Redis stream key (high → low)."""
    prefix = anomaly_stream_prefix()
    return {sev: f"{prefix}:{sev}" for sev in anomaly_priority_order()}


def anomaly_stream_for_severity(severity_type: str) -> str:
    """Resolve the destination stream for an anomaly's severity_type.

    Unknown/missing severities fall back to the lowest-priority stream so a
    misclassified job is still processed (just last)."""
    streams = anomaly_severity_streams()
    return streams.get((severity_type or "").strip().lower(), streams["low"])


def anomaly_dlq_stream() -> str:
    return f"{anomaly_stream_prefix()}:dlq"


def anomaly_max_retries() -> int:
    """How many times a job may be retried before being sent to the DLQ."""
    return int(os.getenv("ANOMALY_MAX_RETRIES", "3"))


# --- Detection: rate-of-change + statistical (env-gated, default off) ---------
# These run alongside the static threshold detector. They are count-based
# (over the last N readings) rather than time-based, because the simulator /
# pipeline runs intermittently.


def anomaly_window_size() -> int:
    """How many recent readings to retain per (sensor, metric)."""
    return int(os.getenv("ANOMALY_WINDOW_SIZE", "20"))


def roc_enabled() -> bool:
    return _truthy(os.getenv("ANOMALY_ROC_ENABLED", "false"))


def roc_pct_threshold() -> float:
    """Fractional change vs the previous reading that triggers an anomaly
    (0.3 = 30%)."""
    return float(os.getenv("ANOMALY_ROC_PCT", "0.3"))


def roc_min_baseline() -> float:
    """Skip rate-of-change when the previous reading's magnitude is below this,
    to avoid divide-by-near-zero noise."""
    return float(os.getenv("ANOMALY_ROC_MIN_BASELINE", "0.001"))


def statistical_enabled() -> bool:
    return _truthy(os.getenv("ANOMALY_STAT_ENABLED", "false"))


def statistical_zscore() -> float:
    """Absolute z-score (vs the rolling baseline) that triggers an outlier."""
    return float(os.getenv("ANOMALY_STAT_ZSCORE", "3.0"))


def statistical_min_readings() -> int:
    """Minimum baseline readings before the statistical detector arms."""
    return int(os.getenv("ANOMALY_STAT_MIN_READINGS", "8"))

