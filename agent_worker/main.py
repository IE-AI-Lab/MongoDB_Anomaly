"""Entrypoint: python -m agent_worker.main"""

from __future__ import annotations

import logging

from dotenv import load_dotenv

from .consumer import run_consumer
from .observability import init_langsmith, setup_worker_observability


def main() -> None:
    load_dotenv()
    init_langsmith()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [agent_worker] %(message)s",
    )
    setup_worker_observability()
    run_consumer()


if __name__ == "__main__":
    main()
