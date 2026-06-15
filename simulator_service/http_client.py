"""
HTTP client for simulator -> ingestor delivery.

This module exists so the simulator core does not depend on requests details.
Later, you can swap this with Kafka/Rabbit/etc and keep the simulator unchanged.
"""

from __future__ import annotations

import time
from typing import Any

import requests


def post_telemetry(base_url: str, payload: dict[str, Any], timeout_seconds: float = 5.0) -> None:
    """
    Send one telemetry payload to the ingestor.

    Reliability (simple v1):
    - retry a few times with small backoff on network/5xx failures.
    - do not retry on 4xx (payload is invalid; retry won't help).
    """
    url = f"{base_url.rstrip('/')}/ingest/telemetry"

    retries = 3
    backoff = 0.5

    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=timeout_seconds)
            if 200 <= resp.status_code < 300:
                return
            if 400 <= resp.status_code < 500:
                raise RuntimeError(f"Ingest rejected ({resp.status_code}): {resp.text}")
            # 5xx: retry
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Failed to POST telemetry after retries: {exc}") from exc
        time.sleep(backoff)
        backoff *= 2


def get_simulation_status(base_url: str, timeout_seconds: float = 3.0) -> bool:
    """
    Return whether the simulator should currently emit (run/pause flag).

    Fail-open: any error (endpoint missing, network blip, old ingestor) returns
    True so a control-plane hiccup never freezes the simulator.
    """
    url = f"{base_url.rstrip('/')}/simulation/status"
    try:
        resp = requests.get(url, timeout=timeout_seconds)
        if 200 <= resp.status_code < 300:
            return bool(resp.json().get("running", True))
    except (requests.RequestException, ValueError):
        pass
    return True

