"""Tests for per-user daily analysis budgets and proxy-aware rate-limit keys."""
from datetime import datetime, timezone
from uuid import uuid4

import main
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import hash_password
from database import engine
from models import User, SpecSession

main.limiter.enabled = False
# Keep the budget test free of infrastructure dependencies
import asyncio
main.dispatch_run = lambda run_id: asyncio.sleep(0)
client = TestClient(main.app)


def _make_user(email: str = "budget@example.com") -> User:
    with Session(engine) as db:
        user = User(
            email=email,
            password_hash=hash_password("password123"),
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _seed_sessions(user: User, count: int) -> None:
    with Session(engine) as db:
        for _ in range(count):
            db.add(SpecSession(
                raw_spec="s",
                user_id=user.id,
                created_at=datetime.now(timezone.utc),
            ))
        db.commit()


def test_authenticated_user_under_limit_passes(monkeypatch):
    monkeypatch.setattr(main, "PER_USER_DAILY_LIMIT", 3)
    user = _make_user("underlimit@example.com")
    _seed_sessions(user, 2)
    main.reserve_daily_session(user)  # must not raise


def test_authenticated_user_over_limit_gets_429(monkeypatch):
    monkeypatch.setattr(main, "PER_USER_DAILY_LIMIT", 2)
    user = _make_user("overlimit@example.com")
    _seed_sessions(user, 2)
    with __import__("pytest").raises(HTTPException) as exc_info:
        main.reserve_daily_session(user)
    assert exc_info.value.status_code == 429


def test_guest_skips_per_user_check_but_reserves_global(monkeypatch):
    monkeypatch.setattr(main, "DAILY_SESSION_LIMIT", 10**6)
    main.reserve_daily_session(None)  # must not raise


def test_client_key_uses_forwarded_for_when_trusted(monkeypatch):
    monkeypatch.setattr(main, "TRUST_PROXY", True)
    request = type("R", (), {"headers": {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, "client": None})()
    assert main.client_key(request) == "203.0.113.7"


def test_client_key_falls_back_to_remote_address():
    request = type("R", (), {"headers": {"x-forwarded-for": "203.0.113.7"}, "client": type("C", (), {"host": "198.51.100.2"})()})()
    assert main.client_key(request) == "198.51.100.2"


def test_end_to_end_user_budget_blocks_fourth_session(monkeypatch):
    monkeypatch.setattr(main, "PER_USER_DAILY_LIMIT", 2)
    r = client.post("/auth/signup", json={"email": "e2e-budget@example.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    for _ in range(2):
        resp = client.post("/sessions", json={"raw_spec": "spec text", "selected_critics": ["assumption"]}, headers=headers)
        assert resp.status_code == 200

    third = client.post("/sessions", json={"raw_spec": "spec text", "selected_critics": ["assumption"]}, headers=headers)
    assert third.status_code == 429
