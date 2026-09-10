"""Small Redis adapter: ARQ job queue for analyses, pub/sub for live run events.

Job enqueueing goes through ARQ (see worker.py); API processes never touch
queue internals directly — deps.dispatch_run is the single enqueue seam.
"""
from __future__ import annotations

import json
import logging
import os
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job
from redis import asyncio as redis

logger = logging.getLogger(__name__)

ARQ_QUEUE_NAME = os.getenv("ARQ_QUEUE_NAME", "specadversary:arq")
EVENT_CHANNEL_PREFIX = os.getenv("RUN_EVENT_CHANNEL_PREFIX", "specadversary:run-events:")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

_client = None

def client():
    global _client
    if _client is None:
        # Short connect timeout: callers degrade gracefully (queue errors are
        # retried by the worker loop; pub/sub falls back to DB polling).
        _client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
            health_check_interval=30,
        )
    return _client


async def publish_event(run_id: UUID, sequence: int, event: dict) -> None:
    """Push one persisted run event to live WebSocket subscribers.

    The sequence number travels with the event so clients can drop
    duplicates when pub/sub delivery overlaps history replay.
    """
    envelope = json.dumps({"seq": sequence, "event": event})
    await client().publish(f"{EVENT_CHANNEL_PREFIX}{run_id}", envelope)


async def subscribe_run(run_id: UUID):
    """Subscribe to a run's live event channel; caller owns closing."""
    pubsub = client().pubsub()
    await pubsub.subscribe(f"{EVENT_CHANNEL_PREFIX}{run_id}")
    return pubsub


async def abort_arq_job(run_id: str) -> bool:
    """Best-effort abort of a queued or running ARQ job by run id.

    True when the abort landed (queued job dequeued, or running job handed
    a CancelledError that execute_run turns into a cancelled run). False
    when Redis is unreachable or no such job exists. Callers must still
    land the DB transition — it is authoritative, this is only the stop
    signal to the worker.
    """
    try:
        pool = await create_pool(
            RedisSettings.from_dsn(REDIS_URL), default_queue_name=ARQ_QUEUE_NAME
        )
    except Exception:
        logger.warning("ARQ abort failed: no Redis connection", exc_info=True)
        return False
    try:
        return await Job(run_id, pool, ARQ_QUEUE_NAME).abort(timeout=5)
    except Exception:
        logger.warning("ARQ abort failed for run %s", run_id, exc_info=True)
        return False
    finally:
        await pool.close()
