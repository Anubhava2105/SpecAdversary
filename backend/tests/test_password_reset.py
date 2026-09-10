"""Tests for password reset and email verification flows."""
import asyncio
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import routes.auth_routes as auth_routes
from core.auth import EMAIL_TOKEN_VERIFY, hash_token
from db.database import engine
from db.models import EmailToken, User
from main import app

client = TestClient(app)


def _sent(monkeypatch):
    """Capture outbound mail without touching SMTP."""
    messages = []
    monkeypatch.setattr(auth_routes, "send_verification_email", lambda to, token: messages.append(("verify", to, token)))
    monkeypatch.setattr(auth_routes, "send_reset_email", lambda to, token: messages.append(("reset", to, token)))
    return messages


def _user(email) -> User:
    with Session(engine) as db:
        return db.exec(select(User).where(User.email == email)).first()


def test_signup_sends_verification_and_starts_unverified(monkeypatch):
    sent = _sent(monkeypatch)
    r = client.post("/auth/signup", json={"email": "verify-me@example.com", "password": "password123"})
    assert r.status_code == 200
    assert r.json()["user"]["email_verified"] is False
    assert _user("verify-me@example.com").email_verified is False
    assert [(kind, to) for kind, to, _ in sent] == [("verify", "verify-me@example.com")]
    with Session(engine) as db:
        row = db.exec(
            select(EmailToken).where(EmailToken.token_hash == hash_token(sent[0][2]))
        ).first()
        assert row is not None and row.purpose == EMAIL_TOKEN_VERIFY and row.used_at is None


def test_verify_email_happy_path_and_single_use(monkeypatch):
    sent = _sent(monkeypatch)
    client.post("/auth/signup", json={"email": "confirm@example.com", "password": "password123"})
    token = sent[0][2]
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    assert _user("confirm@example.com").email_verified is True
    # Reuse is rejected: tokens are single-use.
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 401


def test_verify_email_rejects_garbage():
    assert client.post("/auth/verify-email", json={"token": "x" * 43}).status_code == 401


def test_forgot_password_never_enumerates(monkeypatch):
    sent = _sent(monkeypatch)
    client.post("/auth/signup", json={"email": "exists@example.com", "password": "password123"})
    assert client.post("/auth/forgot-password", json={"email": "exists@example.com"}).status_code == 200
    assert client.post("/auth/forgot-password", json={"email": "nobody@example.com"}).status_code == 200
    assert [(kind, to) for kind, to, _ in sent if kind == "reset"] == [("reset", "exists@example.com")]


def test_reset_password_full_cycle(monkeypatch):
    sent = _sent(monkeypatch)
    signup = client.post("/auth/signup", json={"email": "resetme@example.com", "password": "password123"})
    old_refresh = signup.json()["refresh_token"]
    client.post("/auth/forgot-password", json={"email": "resetme@example.com"})
    token = [t for kind, _, t in sent if kind == "reset"][0]

    assert client.post("/auth/reset-password", json={"token": token, "password": "newpassword456"}).status_code == 200
    # Token is spent.
    assert client.post("/auth/reset-password", json={"token": token, "password": "another7890"}).status_code == 401
    # New password works, old does not.
    assert client.post("/auth/login", json={"email": "resetme@example.com", "password": "newpassword456"}).status_code == 200
    assert client.post("/auth/login", json={"email": "resetme@example.com", "password": "password123"}).status_code == 401
    # Reset logged every session out: the pre-reset refresh token is dead.
    assert client.post("/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401


def test_reset_password_rejects_garbage():
    assert client.post("/auth/reset-password", json={"token": "y" * 43, "password": "newpassword456"}).status_code == 401


def test_resend_verification_requires_unverified():
    signup = client.post("/auth/signup", json={"email": "resend@example.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    assert client.post("/auth/resend-verification", headers=headers).status_code == 200
    assert client.post("/auth/resend-verification").status_code == 401


def test_oauth_accounts_skip_verification():
    user_id = asyncio.run(auth_routes._oauth_upsert("google", "oauth-1", "oauthuser@example.com", "O User", True))
    with Session(engine) as db:
        user = db.get(User, UUID(user_id["user"]["id"]))
        assert user is not None and user.email_verified is True


def test_me_reports_verification_flag():
    signup = client.post("/auth/signup", json={"email": "meflag@example.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    assert client.get("/auth/me", headers=headers).json()["email_verified"] is False
