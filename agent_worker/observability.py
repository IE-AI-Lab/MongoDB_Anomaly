"""Agent-worker observability bootstrap (LangSmith + optional OTEL hook)."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


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
