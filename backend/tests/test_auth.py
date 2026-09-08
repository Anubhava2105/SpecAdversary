from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import Session

from db.database import engine
from db.models import RefreshToken, User
from main import app

client = TestClient(app)


def test_signup_creates_user():
    response = client.post(
        "/auth/signup",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "test@example.com"

    with Session(engine) as db:
        user = db.get(User, UUID(data["user"]["id"]))
        assert user is not None
        assert user.password_hash is not None


def test_signup_duplicate_email():
    client.post("/auth/signup", json={"email": "dup@example.com", "password": "password123"})
    response = client.post("/auth/signup", json={"email": "dup@example.com", "password": "password123"})
    assert response.status_code == 409


def test_login_success():
    client.post("/auth/signup", json={"email": "login@example.com", "password": "password123"})
    response = client.post("/auth/login", json={"email": "login@example.com", "password": "password123"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "login@example.com"


def test_login_invalid_password():
    client.post("/auth/signup", json={"email": "badpass@example.com", "password": "password123"})
    response = client.post("/auth/login", json={"email": "badpass@example.com", "password": "wrongpassword"})
    assert response.status_code == 401


def test_email_matching_is_case_insensitive():
    client.post("/auth/signup", json={"email": "CaseUser@example.com", "password": "password123"})
    dup = client.post("/auth/signup", json={"email": "caseuser@EXAMPLE.com", "password": "password123"})
    assert dup.status_code == 409  # same account, not a second row

    login = client.post("/auth/login", json={"email": "CASEUSER@example.com", "password": "password123"})
    assert login.status_code == 200
    assert login.json()["user"]["email"] == "caseuser@example.com"  # stored normalized


def test_logout_revokes_even_expired_refresh_token():
    signup = client.post("/auth/signup", json={"email": "expired-logout@example.com", "password": "password123"})
    user_id = UUID(signup.json()["user"]["id"])
    # Forge an expired token for the same user: signature valid, exp in the past.
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt

    from core import auth as auth_module

    expired = pyjwt.encode(
        {"sub": str(user_id), "type": "refresh", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        auth_module.JWT_SECRET,
        algorithm=auth_module.JWT_ALGORITHM,
    )
    resp = client.post("/auth/logout", json={"refresh_token": expired})
    assert resp.status_code == 200
    with Session(engine) as db:
        rows = db.exec(__import__("sqlmodel").select(RefreshToken).where(RefreshToken.user_id == user_id)).all()
        assert rows and all(r.revoked for r in rows)


def test_guest_session_creation():
    response = client.post(
        "/sessions",
        json={"raw_spec": "Guest spec", "selected_critics": ["assumption"]}
    )
    assert response.status_code == 200
    session_id = response.json()["id"]

    # Guest can access it
    get_resp = client.get(f"/sessions/{session_id}")
    assert get_resp.status_code == 200


def test_authenticated_session_creation():
    auth_resp = client.post("/auth/signup", json={"email": "auth@example.com", "password": "password123"})
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/sessions",
        json={"raw_spec": "Auth spec", "selected_critics": ["assumption"]},
        headers=headers
    )
    assert response.status_code == 200
    session_id = response.json()["id"]

    # Authenticated user can access it
    get_resp = client.get(f"/sessions/{session_id}", headers=headers)
    assert get_resp.status_code == 200

    # Another user cannot access it
    other_resp = client.post("/auth/signup", json={"email": "other@example.com", "password": "password123"})
    other_token = other_resp.json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    get_resp2 = client.get(f"/sessions/{session_id}", headers=other_headers)
    assert get_resp2.status_code == 403


def test_claim_session_on_signup():
    guest_resp = client.post(
        "/sessions",
        json={"raw_spec": "To be claimed", "selected_critics": ["assumption"]}
    )
    session_id = guest_resp.json()["id"]

    auth_resp = client.post(
        "/auth/signup",
        json={
            "email": "claimer@example.com",
            "password": "password123",
            "claim_session_id": session_id
        }
    )
    assert auth_resp.status_code == 200
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Now the session is owned by the claimer
    list_resp = client.get("/sessions", headers=headers)
    assert list_resp.status_code == 200
    assert any(s["id"] == session_id for s in list_resp.json())
