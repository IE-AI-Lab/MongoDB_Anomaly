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
