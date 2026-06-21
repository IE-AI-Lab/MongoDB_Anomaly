"""
CLI entrypoint for the simulator service.
"""

from __future__ import annotations

import argparse

from .runner import run


def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments.

    Keeping this small makes it easy to run locally and later in containers.
    """
    p = argparse.ArgumentParser(description="Telemetry simulator")
    p.add_argument("--base-url", required=True, help="Ingestor base URL, e.g. http://localhost:8000")
    p.add_argument("--tick-seconds", type=int, default=5, help="Seconds between ticks")
    p.add_argument(
        "--emit-probability",
        type=float,
        default=0.7,
        help="Per-sensor probability a HEALTHY sensor emits on a given tick (0..1). "
        "Faulted/recovering sensors always emit.",
    )
    p.add_argument(
        "--deterministic-demo",
        action="store_true",
        help="Raise every machine's effective degradation rate to a floor so a fresh "
        "demo trips anomalies promptly (overrides low sim_stress sliders).",
    )
    return p.parse_args()


def main() -> None:
    """Start the simulator loop."""
    args = parse_args()
    run(
        base_url=args.base_url,
        tick_seconds=args.tick_seconds,
        emit_probability=args.emit_probability,
        deterministic_demo=args.deterministic_demo,
    )


if __name__ == "__main__":
    main()

