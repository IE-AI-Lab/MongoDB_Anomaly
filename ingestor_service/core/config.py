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
    return os.getenv("OTEL_SERVICE_NAME", default)

