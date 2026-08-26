"""Tests for the production configuration guard."""
import pytest

import deps
import main


def test_dev_environment_never_blocks(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", False)
    monkeypatch.setenv("JWT_SECRET", "dev-insecure-change-me-in-production")
    main.validate_production_config()  # must not raise


def test_production_rejects_default_jwt_secret(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", "dev-insecure-change-me-in-production")
    monkeypatch.setenv("FRONTEND_URL", "https://specadversary.com")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main.validate_production_config()


def test_production_rejects_short_jwt_secret(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", "too-short")
    monkeypatch.setenv("FRONTEND_URL", "https://specadversary.com")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main.validate_production_config()


def test_production_rejects_localhost_frontend_url(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5174")
    with pytest.raises(RuntimeError, match="FRONTEND_URL"):
        main.validate_production_config()


def test_production_accepts_valid_configuration(monkeypatch):
    monkeypatch.setattr(deps, "IS_PRODUCTION", True)
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("FRONTEND_URL", "https://specadversary.com")
    main.validate_production_config()  # must not raise

