"""ARQ-backed durable analysis worker. Run as `python worker.py`.

Concurrency model: ARQ runs up to WORKER_CONCURRENCY analysis jobs in one
process (default 2 — DB access is synchronous SQLModel sessions inside async
code, so keep this small; scale out with more worker replicas instead).
ARQ's default bounded retries stay enabled and are safe: execute_run only
acts on `queued` runs, so a redelivery after a successful claim is a no-op,
while a crash *before* the claim (status still `queued`) legitimately reruns.
Anything stranger is caught by reap_stuck_runs (every minute via ARQ cron,
unique across replicas), which fails orphaned runs terminally.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from arq import cron
from arq.connections import RedisSettings
from arq.typing import StartupShutdown, WorkerSettingsBase
from arq.worker import run_worker

from core.broker import ARQ_QUEUE_NAME, REDIS_URL
from core.logging_config import setup_logging
from core.observability import init_sentry
from services.pipeline_runner import PIPELINE_TIMEOUT_SECONDS, execute_run, reap_stuck_runs

setup_logging()
logger = logging.getLogger(__name__)

WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "2"))
# Slightly above the in-process pipeline timeout: ARQ cancels the job past
# this point, which surfaces as CancelledError and marks the run cancelled.
JOB_TIMEOUT_SECONDS = PIPELINE_TIMEOUT_SECONDS + 60

# In-process gauge for the Phase-4 metrics story (queue depth comes from
# ARQ/Redis itself). Logged on every job boundary; cheap and greppable.
_in_flight = 0


async def run_analysis_job(ctx: dict, run_id: str) -> None:
    """Execute one queued analysis run. run_id travels as str (ARQ JSON args)."""
    global _in_flight
    _in_flight += 1
    logger.info("job start run=%s in_flight=%d", run_id, _in_flight)
    try:
        try:
            import sentry_sdk

            sentry_sdk.set_tag("run_id", run_id)
        except Exception:
            pass
        await execute_run(UUID(run_id))
    finally:
        _in_flight -= 1
        logger.info("job finish run=%s in_flight=%d", run_id, _in_flight)


async def reap_stuck_runs_job(ctx: dict) -> None:
    """Periodic orphan sweep. Cron is unique across replicas by default."""
    try:
        reaped = await reap_stuck_runs()
    except Exception:
        logger.exception("Stuck-run sweep failed")
    else:
        if reaped:
            logger.warning("Reaped %d stuck runs", len(reaped))


async def _on_startup(ctx: dict[Any, Any]) -> None:
    init_sentry("worker")


class WorkerSettings(WorkerSettingsBase):
    functions = [run_analysis_job]
    cron_jobs = [cron(reap_stuck_runs_job, name="reap-stuck-runs", timeout=120)]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    queue_name = ARQ_QUEUE_NAME
    max_jobs = WORKER_CONCURRENCY
    job_timeout = JOB_TIMEOUT_SECONDS
    # Results are persisted in our own RunEvent ledger; don't pay Redis
    # to keep copies of job return values.
    keep_result = 0
    on_startup: StartupShutdown | None = _on_startup


if __name__ == "__main__":
    run_worker(WorkerSettings)
