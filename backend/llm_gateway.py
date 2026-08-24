"""Single, observable boundary for OpenAI-compatible model providers."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger("llm")
_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(max_retries=0)
    return _client


async def completion_message(
    client: AsyncOpenAI, *, model: str, messages: list[dict[str, Any]], timeout: float,
    operation: str, retries: int = 0, **kwargs: Any,
):
    """Return a validated first message and log one structured outcome per attempt."""
    last_error = None
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(model=model, messages=messages, **kwargs), timeout=timeout
            )
            choices = getattr(response, "choices", None)
            if not choices or choices[0].message is None:
                raise RuntimeError("Provider returned a completion without choices or message")
            usage = getattr(response, "usage", None)
            logger.info(
                "llm_completion operation=%s model=%s attempt=%d latency_ms=%d prompt_tokens=%s completion_tokens=%s",
                operation, model, attempt + 1, (time.perf_counter() - started) * 1000,
                getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None),
            )
            return choices[0].message
        except Exception as exc:
            last_error = exc
            logger.warning(
                "llm_completion_failed operation=%s model=%s attempt=%d latency_ms=%d error=%s",
                operation, model, attempt + 1, (time.perf_counter() - started) * 1000, type(exc).__name__,
            )
            if attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"LLM operation '{operation}' failed") from last_error


async def stream_completion(
    client: AsyncOpenAI, *, model: str, messages: list[dict[str, Any]], timeout: float, operation: str,
):
    """Create a streaming completion while recording provider-connect latency."""
    started = time.perf_counter()
    try:
        stream = await asyncio.wait_for(
            client.chat.completions.create(model=model, messages=messages, stream=True), timeout=timeout
        )
        logger.info("llm_stream_connected operation=%s model=%s latency_ms=%d", operation, model, (time.perf_counter() - started) * 1000)
        return stream
    except Exception:
        logger.exception("llm_stream_failed operation=%s model=%s", operation, model)
        raise
