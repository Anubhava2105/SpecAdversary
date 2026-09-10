"""Tests for the Sentry bootstrap (core.observability)."""
from core.observability import init_sentry


def test_sentry_disabled_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry("api") is False


def test_sentry_enabled_with_dsn(monkeypatch):
    # Never arm a real client in the suite (it would flush events at exit).
    import sentry_sdk

    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")
    assert init_sentry("worker") is True
    assert calls and calls[0]["dsn"] == "https://public@example.com/1"
    assert calls[0]["send_default_pii"] is False
