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
        help="Per-sensor probability of emitting on a given tick (0..1)",
    )
    p.add_argument("--prob-low", type=float, default=0.08, help="Probability of low fault per emitted reading")
    p.add_argument("--prob-med", type=float, default=0.04, help="Probability of medium fault per emitted reading")
    p.add_argument("--prob-high", type=float, default=0.02, help="Probability of high fault per emitted reading")
    p.add_argument(
        "--deterministic-demo",
        action="store_true",
        help="Inject guaranteed anomaly every --demo-interval-ticks",
    )
    p.add_argument(
        "--demo-interval-ticks",
        type=int,
        default=10,
        help="Tick interval for deterministic guaranteed anomaly injection",
    )
    return p.parse_args()


def main() -> None:
    """Start the simulator loop."""
    args = parse_args()
    run(
        base_url=args.base_url,
        tick_seconds=args.tick_seconds,
        emit_probability=args.emit_probability,
        prob_low=args.prob_low,
        prob_med=args.prob_med,
        prob_high=args.prob_high,
        deterministic_demo=args.deterministic_demo,
        demo_interval_ticks=args.demo_interval_ticks,
    )


if __name__ == "__main__":
    main()

