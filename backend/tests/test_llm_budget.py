"""Tests for gateway token-budget enforcement and per-operation model tiering."""
import asyncio
from types import SimpleNamespace

import pytest

from services import llm_gateway
from services.llm_gateway import (
    BudgetExceeded,
    begin_token_budget,
    charge_tokens,
    completion_message,
    end_token_budget,
    model_for,
    stream_completion,
)


def _fake_client(prompt_tokens: int = 1000, completion_tokens: int = 500):
    async def create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


# ── Model tiering ─────────────────────────────────────────────────────────
def test_parse_operations_use_fast_tier():
    assert model_for("structured_parse") == llm_gateway.MODEL_FAST
    assert model_for("strict_parse") == llm_gateway.MODEL_FAST


def test_critique_and_synthesis_use_main_tier():
    assert model_for("competitor_tool_loop") == llm_gateway.MODEL_MAIN
    assert model_for("markdown_synthesis") == llm_gateway.MODEL_MAIN


def test_explicit_model_overrides_tier():
    seen = {}

    async def create(**kwargs):
        seen["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    asyncio.run(completion_message(
        client, messages=[], timeout=5, operation="structured_parse", model="custom/model",
    ))
    assert seen["model"] == "custom/model"


# ── Token budget ──────────────────────────────────────────────────────────
def test_charges_accumulate_and_trip_budget():
    begin_token_budget(limit=2000)
    charge_tokens(1000, 500)   # 1500 — under
    with pytest.raises(BudgetExceeded):
        charge_tokens(400, 200)  # 2100 — over


def test_completion_message_charges_reported_usage():
    begin_token_budget(limit=10**9)
    asyncio.run(completion_message(_fake_client(300, 200), messages=[], timeout=5, operation="structured_parse"))
    assert end_token_budget() == 500


def test_completion_message_raises_when_budget_exhausted():
    begin_token_budget(limit=800)
    with pytest.raises(BudgetExceeded):
        asyncio.run(completion_message(_fake_client(600, 400), messages=[], timeout=5, operation="strict_parse"))


def test_no_budget_active_means_free_spending():
    end_token_budget()
    charge_tokens(10**9, 10**9)  # must not raise outside a run scope


def test_only_successful_attempt_is_charged():
    calls = {"n": 0}

    async def create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient provider error")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    begin_token_budget(limit=10**9)
    asyncio.run(completion_message(client, messages=[], timeout=5, operation="structured_parse", retries=2))
    assert calls["n"] == 2           # first attempt failed, second succeeded
    assert end_token_budget() == 150  # only the successful attempt is charged


# ── Streaming budget ────────────────────────────────────────────────────
def _stream_client(chunks: list[str]):
    async def gen():
        for c in chunks:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=c))])

    async def create(**kwargs):
        return gen()

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_long_stream_trips_budget_mid_stream():
    begin_token_budget(limit=10)  # ~10 tokens ≈ 40 chars
    stream = asyncio.run(stream_completion(_stream_client(["x" * 20] * 10), messages=[], timeout=5, operation="markdown_synthesis"))

    async def drain():
        async for _ in stream:
            pass

    with pytest.raises(BudgetExceeded):
        asyncio.run(drain())


def test_empty_stream_charges_nothing():
    begin_token_budget(limit=10**9)
    stream = asyncio.run(stream_completion(_stream_client([]), messages=[], timeout=5, operation="markdown_synthesis"))

    async def drain():
        async for _ in stream:
            pass

    asyncio.run(drain())
    assert end_token_budget() == 0  # failed/empty streams cost nothing


# ── Per-run model tiering ─────────────────────────────────────────────
def test_guest_tier_routes_everything_to_guest_model():
    assert model_for("structured_parse", "guest") == llm_gateway.MODEL_GUEST
    assert model_for("markdown_synthesis", "guest") == llm_gateway.MODEL_GUEST


def test_paid_tier_keeps_parse_cheap_and_critique_strong():
    assert model_for("structured_parse", "paid") == llm_gateway.MODEL_FAST
    assert model_for("markdown_synthesis", "paid") == llm_gateway.MODEL_PAID


def test_unknown_tier_falls_back_to_standard():
    assert model_for("markdown_synthesis", "platinum") == llm_gateway.MODEL_MAIN
    assert model_for("structured_parse", "platinum") == llm_gateway.MODEL_FAST


def test_run_context_tier_applies_without_explicit_argument():
    llm_gateway.set_run_tier("guest")
    try:
        assert model_for("markdown_synthesis") == llm_gateway.MODEL_GUEST
    finally:
        llm_gateway.set_run_tier(None)
    assert model_for("markdown_synthesis") == llm_gateway.MODEL_MAIN


def test_resolve_run_tier_maps_guests_to_guest():
    assert llm_gateway.resolve_run_tier(True) == "guest"
    assert llm_gateway.resolve_run_tier(False) == "standard"


def test_tier_kwarg_reaches_provider_call():
    seen = {}

    async def create(**kwargs):
        seen["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    asyncio.run(completion_message(
        client, messages=[], timeout=5, operation="markdown_synthesis", tier="guest",
    ))
    assert seen["model"] == llm_gateway.MODEL_GUEST
