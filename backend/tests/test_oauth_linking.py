"""Regression tests: OAuth email-based account linking must require verification."""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from core.auth import hash_password
from db.database import engine
from db.models import User
from main import _oauth_upsert


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


def _get_user(email: str) -> User | None:
    with Session(engine) as db:
        return db.exec(select(User).where(User.email == email)).first()


def test_unverified_email_cannot_hijack_password_account():
    victim = _make_password_user("victim@example.com")

    with __import__("pytest").raises(HTTPException) as exc_info:
        asyncio.run(_oauth_upsert("github", "attacker-id", "victim@example.com", "Attacker", False))
    assert exc_info.value.status_code == 400

    linked = _get_user("victim@example.com")
    assert linked is not None
    assert str(linked.id) == str(victim.id)
    assert linked.oauth_provider is None  # Account was NOT linked
    assert linked.password_hash is not None


def test_verified_email_links_existing_account():
    _make_password_user("owner@example.com")
    result = asyncio.run(_oauth_upsert("google", "g-id-1", "owner@example.com", "Owner", True))
    assert "access_token" in result

    linked = _get_user("owner@example.com")
    assert linked is not None
    assert linked.oauth_provider == "google"
    assert linked.oauth_provider_id == "g-id-1"


def test_verified_email_creates_new_user():
    result = asyncio.run(_oauth_upsert("github", "gh-id-9", "newuser@example.com", "New", True))
    assert result["user"]["email"] == "newuser@example.com"

    created = _get_user("newuser@example.com")
    assert created is not None
    assert created.oauth_provider == "github"


def test_unverified_email_never_creates_account():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_oauth_upsert("google", "g-id-2", "fresh@example.com", "Fresh", False))
    assert exc_info.value.status_code == 400
    assert _get_user("fresh@example.com") is None


def test_second_provider_does_not_clobber_first_link():
    asyncio.run(_oauth_upsert("google", "g-multi-1", "multi@example.com", "Multi", True))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_oauth_upsert("github", "gh-multi-1", "multi@example.com", "Multi", True))
    assert exc_info.value.status_code == 409

    linked = _get_user("multi@example.com")
    assert linked is not None
    assert linked.oauth_provider == "google"  # first link intact
    assert linked.oauth_provider_id == "g-multi-1"


def test_linking_matches_email_case_insensitively():
    _make_password_user("mixedcase@example.com")
    result = asyncio.run(_oauth_upsert("google", "g-id-9", "MixedCase@Example.COM", "Mixed", True))
    assert "access_token" in result
    found = _get_user("mixedcase@example.com")
    assert found is not None
    assert found.oauth_provider == "google"
