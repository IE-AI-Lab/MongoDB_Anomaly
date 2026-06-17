"""Environment configuration for the agent worker process."""

from __future__ import annotations

import os


def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def anomaly_stream_key() -> str:
    return os.getenv("ANOMALY_STREAM_KEY", "anomaly:jobs")


def anomaly_consumer_group() -> str:
    return os.getenv("ANOMALY_CONSUMER_GROUP", "agent-workers")


# --- Hybrid severity-based Redis routing -------------------------------------
# Mirrors ingestor_service.core.config (separate process). The worker drains
# {prefix}:high before :medium before :low, and routes exhausted jobs to
# {prefix}:dlq.


def anomaly_stream_prefix() -> str:
    return os.getenv("ANOMALY_STREAM_PREFIX", "anomaly")


def anomaly_priority_order() -> list[str]:
    """Severity buckets in descending priority."""
    return ["high", "medium", "low"]


def anomaly_severity_streams() -> dict[str, str]:
    """Map each severity bucket to its Redis stream key (high → low)."""
    prefix = anomaly_stream_prefix()
    return {sev: f"{prefix}:{sev}" for sev in anomaly_priority_order()}


def anomaly_priority_streams() -> list[str]:
    """Stream keys in the order the worker should drain them."""
    streams = anomaly_severity_streams()
    return [streams[sev] for sev in anomaly_priority_order()]


def anomaly_dlq_stream() -> str:
    return f"{anomaly_stream_prefix()}:dlq"


def anomaly_max_retries() -> int:
    """How many times a job may be retried before being sent to the DLQ."""
    return int(os.getenv("ANOMALY_MAX_RETRIES", "3"))


def anomaly_stream_maxlen() -> int:
    return int(os.getenv("ANOMALY_STREAM_MAXLEN", "10000"))


def consumer_name() -> str:
    return os.getenv("AGENT_CONSUMER_NAME", "worker-1")


def consumer_block_ms() -> int:
    return int(os.getenv("AGENT_CONSUMER_BLOCK_MS", "20000"))


def data_layer_base_url() -> str:
    return os.getenv("DATA_LAYER_BASE_URL", "http://localhost:8000").rstrip("/")


# --- Chat / agent reasoning: DeepSeek (OpenAI-compatible endpoint) ------------
# The investigation agent uses langchain_openai.ChatOpenAI — the generic client
# for the OpenAI chat-completions *wire format*. It does NOT call OpenAI; DeepSeek
# implements that same format, so the client points at LLM_BASE_URL. Configure:
#   LLM_BASE_URL  - OpenAI-compatible base (default DeepSeek)
#   LLM_API_KEY   - key for that provider (falls back to DEEPSEEK_API_KEY)
#   CHAT_MODEL    - model id (default deepseek-v4-flash)


def llm_api_key() -> str:
    """API key for the DeepSeek (OpenAI-compatible) LLM provider. Empty ⇒ the
    graph skips LLM reasoning and uses the deterministic fallback (worker runs)."""
    return os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")


def llm_base_url() -> str:
    """OpenAI-compatible base URL (default DeepSeek; override via LLM_BASE_URL)."""
    return (os.getenv("LLM_BASE_URL") or "https://api.deepseek.com").rstrip("/")


def chat_model() -> str:
    return os.getenv("CHAT_MODEL", "deepseek-v4-flash")


def otel_enabled() -> bool:
    return os.getenv("OTEL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def otel_exporter_otlp_endpoint() -> str:
    return os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")


def otel_service_name(default: str = "agent_worker") -> str:
    # Empty (OTEL_SERVICE_NAME=) means "unset" — fall back to the per-process
    # default rather than reporting an empty service.name to the collector.
    return os.getenv("OTEL_SERVICE_NAME") or default


# --- Agent identity (written into agent_execution_logs traces) ----------------

AGENT_NAME = "mongodb-anomaly-agent"
AGENT_VERSION = "0.2.0"
