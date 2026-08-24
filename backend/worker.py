"""Dedicated durable analysis worker. Run as `python worker.py`."""
from __future__ import annotations

import asyncio
import logging

from broker import dequeue_run
from pipeline_runner import execute_run

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    while True:
        run_id = await dequeue_run()
        if run_id is not None:
            await execute_run(run_id)


if __name__ == "__main__":
    asyncio.run(main())
