"""Environment configuration for the agent worker process."""

from __future__ import annotations

import os


def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def anomaly_stream_key() -> str:
    return os.getenv("ANOMALY_STREAM_KEY", "anomaly:jobs")


def anomaly_consumer_group() -> str:
    return os.getenv("ANOMALY_CONSUMER_GROUP", "agent-workers")


def consumer_name() -> str:
    return os.getenv("AGENT_CONSUMER_NAME", "worker-1")


def consumer_block_ms() -> int:
    return int(os.getenv("AGENT_CONSUMER_BLOCK_MS", "20000"))


def data_layer_base_url() -> str:
    return os.getenv("DATA_LAYER_BASE_URL", "http://localhost:8000").rstrip("/")


# --- Chat / agent reasoning: Groq (OpenAI-compatible endpoint) ----------------
# Mirrors ingestor_service.config but lives here because the worker is a separate
# process. Used by the OpenAI SDK (NOT the native groq/langchain_groq SDKs — the
# base URL already includes /openai/v1, which those would double up).


def groq_api_key() -> str:
    """Groq API key. Empty ⇒ the graph skips LLM reasoning and uses the
    deterministic fallback, so the worker still runs without a key."""
    return os.getenv("GROQ_API_KEY", "")


def groq_base_url() -> str:
    """OpenAI-compatible endpoint — for the OpenAI SDK only."""
    return os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")


def groq_native_api_base() -> str:
    """Native Groq API root — for langchain_groq.ChatGroq (no /openai/v1 suffix)."""
    raw = os.getenv("GROQ_API_BASE") or os.getenv("GROQ_BASE_URL", "https://api.groq.com")
    return raw.removesuffix("/openai/v1").rstrip("/")


def chat_model() -> str:
    return os.getenv("CHAT_MODEL", "llama-3.3-70b-versatile")


# --- Agent identity (written into agent_execution_logs traces) ----------------

AGENT_NAME = "mongodb-anomaly-agent"
AGENT_VERSION = "0.2.0"
