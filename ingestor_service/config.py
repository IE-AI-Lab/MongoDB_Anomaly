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

