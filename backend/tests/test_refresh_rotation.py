"""Tests for refresh-token rotation, theft detection, and logout revocation."""
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine
from main import app
from models import RefreshToken

client = TestClient(app)


def _signup(email: str = "rotate@example.com") -> dict:
    r = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    return r.json()


def test_refresh_rotates_and_supersedes_old_token():
    tokens = _signup()
    old_refresh = tokens["refresh_token"]

    r = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_pair = r.json()
    assert new_pair["access_token"] != tokens["access_token"]
    assert new_pair["refresh_token"] != old_refresh


def test_reusing_rotated_token_revokes_family():
    tokens = _signup("reuse@example.com")
    first_refresh = tokens["refresh_token"]

    # Legitimate rotation consumes the token
    r1 = client.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert r1.status_code == 200
    second_refresh = r1.json()["refresh_token"]

    # Replay of the already-superseded token must fail...
    replay = client.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401
    assert "reuse" in replay.json()["detail"].lower()

    # ...and the whole family (the newer child token) is now dead too.
    dead = client.post("/auth/refresh", json={"refresh_token": second_refresh})
    assert dead.status_code == 401


def test_logout_revokes_all_user_tokens():
    tokens = _signup("logout@example.com")
    refresh_token = tokens["refresh_token"]

    r = client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert r.status_code == 200

    revoked = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert revoked.status_code == 401


def test_unknown_refresh_token_rejected():
    r = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401


def test_tokens_stored_hashed_not_plaintext():
    tokens = _signup("hashcheck@example.com")
    with Session(engine) as db:
        rows = db.exec(select(RefreshToken)).all()
    assert rows, "expected at least one stored refresh token"
    assert all(row.token_hash != tokens["refresh_token"] for row in rows)
    assert all(len(row.token_hash) == 64 for row in rows)  # sha256 hex digest
