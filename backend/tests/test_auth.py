import pytest
from sqlmodel import Session
from uuid import uuid4, UUID
import database
from sqlmodel import create_engine, SQLModel
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from fastapi.testclient import TestClient

database.engine = create_engine(
    "sqlite://", 
    connect_args={"check_same_thread": False}, 
    poolclass=StaticPool
)

from models import User, SpecSession
from main import app
from database import engine

database.create_db_and_tables()

with database.engine.begin() as conn:
    conn.execute(text("CREATE TABLE IF NOT EXISTS daily_usage (day TEXT PRIMARY KEY, sessions_created INTEGER)"))

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
        user = db.get(User, uuid4(data["user"]["id"]) if False else UUID(data["user"]["id"]))
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
