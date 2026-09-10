"""Tests for refresh-token rotation, theft detection, and logout revocation."""
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from db.database import engine
from db.models import RefreshToken
from main import app

client = TestClient(app)


def _signup(email: str = "rotate@example.com") -> dict:
    r = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    return r.json()


def _refresh_cookie(response) -> str | None:
    """Extract the sa_refresh cookie the server set, if any."""
    raw = response.headers.get("set-cookie", "")
    for part in raw.split(","):
        if part.strip().startswith("sa_refresh="):
            return part.strip().split(";", 1)[0].split("=", 1)[1].strip('"')
    return None


def test_login_sets_httponly_refresh_cookie():
    r = client.post("/auth/signup", json={"email": "cookie@example.com", "password": "password123"})
    assert r.status_code == 200
    jar = r.headers.get("set-cookie", "").lower()
    assert "sa_refresh=" in jar
    assert "httponly" in jar
    assert "samesite=lax" in jar
    assert "path=/auth" in jar


def test_refresh_works_from_cookie_without_body():
    from fastapi.testclient import TestClient as TC

    jar_client = TC(app)
    signup = jar_client.post("/auth/signup", json={"email": "cookierefresh@example.com", "password": "password123"})
    assert signup.status_code == 200
    # TestClient persists cookies: refresh with an empty body, cookie carries it.
    r = jar_client.post("/auth/refresh", json={})
    assert r.status_code == 200
    assert "access_token" in r.json()
    assert _refresh_cookie(r) is not None


def test_logout_clears_cookie():
    from fastapi.testclient import TestClient as TC

    jar_client = TC(app)
    jar_client.post("/auth/signup", json={"email": "cookielogout@example.com", "password": "password123"})
    r = jar_client.post("/auth/logout", json={})
    assert r.status_code == 200
    cleared = r.headers.get("set-cookie", "").lower()
    assert "sa_refresh=" in cleared
    assert "max-age=0" in cleared or 'expires=' in cleared


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
    from core.auth import hash_token

    tokens = _signup("hashcheck@example.com")
    with Session(engine) as db:
        rows = db.exec(select(RefreshToken)).all()
    assert rows, "expected at least one stored refresh token"
    assert all(row.token_hash != tokens["refresh_token"] for row in rows)
    assert any(row.token_hash == hash_token(tokens["refresh_token"]) for row in rows)
