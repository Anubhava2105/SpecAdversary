"""Small Redis queue adapter. API processes enqueue; workers consume."""
from __future__ import annotations

import asyncio
import json
import os
from uuid import UUID

from redis import asyncio as redis
from redis.exceptions import ConnectionError, TimeoutError as RedisTimeoutError

QUEUE_NAME = os.getenv("ANALYSIS_QUEUE_NAME", "specadversary:analysis-runs")
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
