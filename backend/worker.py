"""Dedicated durable analysis worker. Run as `python worker.py`."""
from __future__ import annotations

import asyncio
import logging

from broker import dequeue_run
from pipeline_runner import execute_run, reap_stuck_runs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REAP_INTERVAL_SECONDS = 60


async def main() -> None:
    last_reap = 0.0
    while True:
        run_id = await dequeue_run()
        if run_id is not None:
            await execute_run(run_id)
            continue
        # Idle cycle: opportunistically sweep orphaned runs.
        now = asyncio.get_running_loop().time()
        if now - last_reap >= REAP_INTERVAL_SECONDS:
            try:
                reap_stuck_runs()
            except Exception:
                logger.exception("Stuck-run sweep failed")
            last_reap = now


if __name__ == "__main__":
    asyncio.run(main())
