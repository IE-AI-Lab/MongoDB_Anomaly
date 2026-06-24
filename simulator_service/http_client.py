"""
HTTP client for simulator -> ingestor delivery.

This module exists so the simulator core does not depend on requests details.
Later, you can swap this with Kafka/Rabbit/etc and keep the simulator unchanged.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests


# Anomaly statuses that mean "still open" — the simulator keeps a sensor's breach
# held until none of its anomalies are in one of these (i.e. it was resolved).
_OPEN_STATUSES = frozenset({"unresolved", "processing", "analyzed", "assigned"})


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


def get_sensor_stress(base_url: str, timeout_seconds: float = 3.0) -> Optional[dict[str, float]]:
    """
    Return {sensor_id: sim_stress} from the live sensor fleet (the slider values).

    Returns None on any error so the caller can keep using its cached values
    (and ultimately the per-sensor default) instead of resetting the fleet.
    """
    url = f"{base_url.rstrip('/')}/sensors"
    try:
        resp = requests.get(url, timeout=timeout_seconds)
        if 200 <= resp.status_code < 300:
            out: dict[str, float] = {}
            for s in resp.json():
                sid = s.get("sensor_id")
                if sid is not None and "sim_stress" in s:
                    out[sid] = float(s["sim_stress"])
            return out
    except (requests.RequestException, ValueError, TypeError):
        pass
    return None


def get_open_anomaly_sensors(base_url: str, timeout_seconds: float = 3.0) -> Optional[set[str]]:
    """
    Return the set of sensor_ids that currently have an *open* anomaly (not yet
    resolved). The simulator holds a sensor's breach while it's in this set and
    starts recovering once it drops out (a worker resolved it).

    Returns None on error so the caller leaves modes unchanged that tick rather
    than spuriously recovering every held breach on a transient API blip.
    """
    url = f"{base_url.rstrip('/')}/anomalies"
    try:
        resp = requests.get(url, params={"limit": 200}, timeout=timeout_seconds)
        if 200 <= resp.status_code < 300:
            return {
                a["sensor_id"]
                for a in resp.json()
                if a.get("sensor_id") and a.get("status") in _OPEN_STATUSES
            }
    except (requests.RequestException, ValueError, TypeError):
        pass
    return None

