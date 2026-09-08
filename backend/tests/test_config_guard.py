"""Tests for the production configuration guard."""
import pytest

import main
from core import deps


def test_dev_environment_never_blocks(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", False)
    monkeypatch.setenv("JWT_SECRET", "dev-insecure-change-me-in-production")
    main.validate_production_config()  # must not raise


def test_production_rejects_default_jwt_secret(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", "dev-insecure-change-me-in-production")
    monkeypatch.setenv("FRONTEND_URL", "https://specadversary.com")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://redis:6379/0")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main.validate_production_config()


@pytest.mark.parametrize("secret", ["dev-insecure-change-me-in-production", "too-short"])
def test_production_rejects_unsafe_jwt_secret(monkeypatch, secret):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", secret)
    monkeypatch.setenv("FRONTEND_URL", "https://specadversary.com")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://redis:6379/0")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main.validate_production_config()


def test_production_rejects_localhost_frontend_url(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5174")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://redis:6379/0")
    with pytest.raises(RuntimeError, match="FRONTEND_URL"):
        main.validate_production_config()


def test_production_accepts_valid_configuration(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("FRONTEND_URL", "https://specadversary.com")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://redis:6379/0")
    main.validate_production_config()  # must not raise


def test_production_rejects_memory_rate_limit_storage(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("FRONTEND_URL", "https://specadversary.com")
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    with pytest.raises(RuntimeError, match="RATELIMIT_STORAGE_URI"):
        main.validate_production_config()

