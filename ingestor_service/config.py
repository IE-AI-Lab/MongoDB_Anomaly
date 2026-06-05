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


# --- Embeddings: Google Gemini (free tier) -----------------------------------
# Groq has no embeddings endpoint, so embeddings come from Gemini while chat
# comes from Groq (see below). The vector index in Atlas must match
# embed_dimensions().


def google_api_key() -> str:
    """
    Google AI Studio API key for Gemini embeddings.

    Optional at startup: returns "" when unset so the service can boot without
    RAG configured. rag.py raises a clear error only when an embedding is
    actually requested without a key.
    """
    return os.getenv("GOOGLE_API_KEY", "")


def embed_model() -> str:
    """Gemini embedding model. gemini-embedding-001 supports Matryoshka
    truncation to embed_dimensions() (768/1536/3072)."""
    return os.getenv("EMBED_MODEL", "gemini-embedding-001")


def embed_dimensions() -> int:
    """
    Embedding vector dimensionality.

    Must match the Atlas vector index (step 03) and every stored
    text_embedding. text-embedding-004 = 768.
    """
    return int(os.getenv("EMBED_DIMENSIONS", "768"))


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

