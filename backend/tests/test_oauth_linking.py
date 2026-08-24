"""Regression tests: OAuth email-based account linking must require verification."""
import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlmodel import Session, select

from auth import hash_password
from database import engine
from main import _oauth_upsert
from models import User


def _make_password_user(email: str) -> User:
    with Session(engine) as db:
        user = User(
            email=email,
            password_hash=hash_password("password123"),
            display_name="Victim",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _get_user(email: str) -> User:
    with Session(engine) as db:
        return db.exec(select(User).where(User.email == email)).first()


def test_unverified_email_cannot_hijack_password_account():
    victim = _make_password_user("victim@example.com")

    with __import__("pytest").raises(HTTPException) as exc_info:
        asyncio.run(_oauth_upsert("github", "attacker-id", "victim@example.com", "Attacker", False))
    assert exc_info.value.status_code == 400

    linked = _get_user("victim@example.com")
    assert str(linked.id) == str(victim.id)
    assert linked.oauth_provider is None  # Account was NOT linked
    assert linked.password_hash is not None


def test_verified_email_links_existing_account():
    _make_password_user("owner@example.com")
    result = asyncio.run(_oauth_upsert("google", "g-id-1", "owner@example.com", "Owner", True))
    assert "access_token" in result

    linked = _get_user("owner@example.com")
    assert linked.oauth_provider == "google"
    assert linked.oauth_provider_id == "g-id-1"


def test_verified_email_creates_new_user():
    result = asyncio.run(_oauth_upsert("github", "gh-id-9", "newuser@example.com", "New", True))
    assert result["user"]["email"] == "newuser@example.com"

    created = _get_user("newuser@example.com")
    assert created is not None
    assert created.oauth_provider == "github"


def test_unverified_email_never_creates_account():
    try:
        asyncio.run(_oauth_upsert("google", "g-id-2", "fresh@example.com", "Fresh", False))
    except HTTPException:
        pass
    assert _get_user("fresh@example.com") is None
