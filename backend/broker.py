"""Small Redis queue adapter. API processes enqueue; workers consume."""
from __future__ import annotations

import asyncio
import json
import os
from uuid import UUID

from redis import asyncio as redis
from redis.exceptions import ConnectionError, TimeoutError as RedisTimeoutError

QUEUE_NAME = os.getenv("ANALYSIS_QUEUE_NAME", "specadversary:analysis-runs")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

_client = None

def client():
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


async def enqueue_run(run_id: UUID) -> None:
    await client().rpush(QUEUE_NAME, json.dumps({"run_id": str(run_id)}))


async def dequeue_run(timeout_seconds: int = 5) -> UUID | None:
    try:
        item = await client().blpop(QUEUE_NAME, timeout=timeout_seconds)
        if item is None:
            return None
        _, payload = item
        return UUID(json.loads(payload)["run_id"])
    except (TimeoutError, ConnectionError, RedisTimeoutError, asyncio.exceptions.CancelledError):
        # Ignore read timeouts or transient connection drops and loop again
        return None
