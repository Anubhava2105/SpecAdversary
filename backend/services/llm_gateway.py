"""Single, observable boundary for OpenAI-compatible model providers.

Responsibilities:
- resolve the model per operation (fast tier for mechanical parsing,
  main tier for critique and synthesis) and per run tier (guest versus
  paid routing for monetization),
- structured latency/token logging per attempt,
- enforcement of a cumulative per-run token budget (financial-DoS wall).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger("llm")
_client: AsyncOpenAI | None = None

MODEL_MAIN = os.getenv("OPENAI_MODEL", "gpt-4.1")
MODEL_FAST = os.getenv("OPENAI_MODEL_FAST", MODEL_MAIN)
# Guest runs stay on the cheapest model for every operation; paid runs use
# the mid-tier model for critique/synthesis while parsing stays cheap.
MODEL_GUEST = os.getenv("OPENAI_MODEL_GUEST", MODEL_FAST)
MODEL_PAID = os.getenv("OPENAI_MODEL_PAID", MODEL_MAIN)
# Mechanical parse/moderate operations tolerate the fast tier; adversarial
# critique and user-facing synthesis stay on the main tier.
FAST_OPERATIONS = {"structured_parse", "strict_parse"}
# Known run tiers. Unknown tiers fall back to "standard" (never raise: a
# stale client value must not kill a run).
RUN_TIERS = ("standard", "guest", "paid")
RUN_TOKEN_BUDGET = int(os.getenv("RUN_TOKEN_BUDGET", "150000"))
# Streaming responses may not report usage; estimate from returned characters.
_CHARS_PER_TOKEN_ESTIMATE = 4


class BudgetExceeded(RuntimeError):
    """Raised mid-run when the cumulative token budget is exhausted."""


def model_for(operation: str, tier: str | None = None) -> str:
    """Resolve the model for an operation within a run tier.

    Tier precedence: explicit argument, then the active run context
    (see set_run_tier), then "standard". Unknown tiers fall back to
    "standard" with a warning so stale values degrade gracefully.
    """
    resolved_tier = tier or _tier_var.get() or "standard"
    if resolved_tier not in RUN_TIERS:
        logger.warning("Unknown model tier %r; falling back to 'standard'", resolved_tier)
        resolved_tier = "standard"
    if resolved_tier == "guest":
        return MODEL_GUEST
    if resolved_tier == "paid":
        return MODEL_FAST if operation in FAST_OPERATIONS else MODEL_PAID
    return MODEL_FAST if operation in FAST_OPERATIONS else MODEL_MAIN


def resolve_run_tier(is_guest: bool) -> str:
    """Map a session's ownership to the model tier for its run.

    Guest sessions run fully on the cheap tier today; signed-in sessions
    use the standard mapping until the paywall introduces a real paid tier.
    The paywall and dispatch both read this one function.
    """
    return "guest" if is_guest else "standard"


_tier_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_model_tier", default=None)


def set_run_tier(tier: str | None) -> None:
    """Set the model tier for the current run context (cleared per run)."""
    _tier_var.set(tier)


def get_run_tier() -> str | None:
    """The model tier bound to the current run context, if any."""
    return _tier_var.get()


@dataclass
class _Budget:
    limit: int
    used: int = 0


_budget_var: contextvars.ContextVar[_Budget | None] = contextvars.ContextVar("run_token_budget", default=None)


def begin_token_budget(limit: int = RUN_TOKEN_BUDGET) -> None:
    _budget_var.set(_Budget(limit=limit))


def end_token_budget() -> int:
    """Clear the active budget and return the tokens it recorded."""
    budget = _budget_var.get()
    _budget_var.set(None)
    return budget.used if budget else 0


def charge_tokens(prompt_tokens: int, completion_tokens: int) -> None:
    budget = _budget_var.get()
    if budget is None:
        return
    budget.used += max(0, prompt_tokens) + max(0, completion_tokens)
    if budget.used > budget.limit:
        raise BudgetExceeded(f"Run token budget exhausted ({budget.used}/{budget.limit})")


def budget_remaining() -> int | None:
    """Tokens left in the active budget, or None when no budget is active."""
    budget = _budget_var.get()
    if budget is None:
        return None
    return budget.limit - budget.used


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(max_retries=0)
    return _client


async def completion_message(
    client: AsyncOpenAI, *, messages: list[dict[str, Any]], timeout: float,
    operation: str, model: str | None = None, retries: int = 0, tier: str | None = None,
    **kwargs: Any,
):
    """Return a validated first message and log one structured outcome per attempt."""
    resolved_model = model or model_for(operation, tier)
    last_error = None
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(model=resolved_model, messages=messages, **kwargs),  # type: ignore[arg-type]
                timeout=timeout
            )
            choices = getattr(response, "choices", None)
            if not choices or choices[0].message is None:
                raise RuntimeError("Provider returned a completion without choices or message")
            usage = getattr(response, "usage", None)
            logger.info(
                "llm_completion operation=%s model=%s attempt=%d latency_ms=%d prompt_tokens=%s completion_tokens=%s",
                operation, resolved_model, attempt + 1, (time.perf_counter() - started) * 1000,
                getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None),
            )
            # Charge after logging so the audit line always lands first.
            if usage is not None:
                charge_tokens(
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                )
            return choices[0].message
        except BudgetExceeded:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning(
                "llm_completion_failed operation=%s model=%s attempt=%d latency_ms=%d error=%s",
                operation, resolved_model, attempt + 1, (time.perf_counter() - started) * 1000, type(exc).__name__,
            )
            if attempt < retries:
                err_str = (str(exc) + " " + type(exc).__name__).lower()
                if "429" in err_str or "resource_exhausted" in err_str or "ratelimit" in err_str or "quota" in err_str:
                    await asyncio.sleep(14.0 * (attempt + 1))
                elif "503" in err_str or "unavailable" in err_str or "timeouterror" in err_str:
                    await asyncio.sleep(4.0 * (attempt + 1))
                else:
                    await asyncio.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"LLM operation '{operation}' failed") from last_error


async def stream_completion(
    client: AsyncOpenAI, *, messages: list[dict[str, Any]], timeout: float, operation: str,
    model: str | None = None, tier: str | None = None,
):
    """Create a streaming completion while recording provider-connect latency."""
    resolved_model = model or model_for(operation, tier)
    started = time.perf_counter()
    try:
        stream = await asyncio.wait_for(
            client.chat.completions.create(model=resolved_model, messages=messages, stream=True),  # type: ignore[arg-type]
            timeout=timeout
        )
        logger.info("llm_stream_connected operation=%s model=%s latency_ms=%d", operation, resolved_model, (time.perf_counter() - started) * 1000)
    except BudgetExceeded:
        raise
    except Exception:
        logger.exception("llm_stream_failed operation=%s model=%s", operation, resolved_model)
        raise

    async def guarded():
        characters = 0
        try:
            async for chunk in stream:  # type: ignore[union-attr]
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    characters += len(delta)
                    remaining = budget_remaining()
                    if remaining is not None and characters // _CHARS_PER_TOKEN_ESTIMATE >= remaining:
                        raise BudgetExceeded(
                            f"Run token budget exhausted mid-stream ({characters} chars)"
                        )
                    yield chunk
        finally:
            # Streams rarely report usage; approximate from generated text.
            # Empty (failed) streams charge nothing.
            charge_tokens(0, characters // _CHARS_PER_TOKEN_ESTIMATE)

    return guarded()
