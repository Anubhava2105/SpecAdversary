"""API-level tests for the Risk Register endpoints."""
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import Session

from core import deps
from db.database import engine
from db.models import Risk, SessionStatus, SpecSession
from main import app

# Mock dispatch_run to avoid redis connection (slowapi itself is disabled globally in conftest)
deps.dispatch_run = lambda run_id: __import__("asyncio").sleep(0)

client = TestClient(app)


def _signup(email: str = "risk@example.com") -> tuple[str, dict]:
    r = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


def _create_session_with_risks(headers: dict | None = None) -> tuple[str, list[str]]:
    """Create a completed session and manually insert some Risk rows."""
    r = client.post(
        "/sessions",
        json={"raw_spec": "Test spec for risks", "selected_critics": ["assumption"]},
        headers=headers or {},
    )
    assert r.status_code == 200
    session_id = r.json()["id"]

    # Mark the analysis complete: re-evaluation is only valid post-run.
    with Session(engine) as db:
        row = db.get(SpecSession, UUID(session_id))
        assert row is not None
        row.status = SessionStatus.done
        db.add(row)
        db.commit()

    # Insert risks directly
    risk_ids = []
    with Session(engine) as db:
        for i in range(3):
            risk = Risk(
                session_id=UUID(session_id),
                finding_id=f"finding_{i}",
                critic="assumption",
                severity=["structural", "significant", "minor"][i],
                claim=f"Test claim {i}",
                critique=f"Test critique {i}",
                suggested_fix=f"Fix {i}",
            )
            db.add(risk)
            db.commit()
            db.refresh(risk)
            risk_ids.append(str(risk.id))

    return session_id, risk_ids


# ── List risks ─────────────────────────────────────────────────────────────
def test_list_risks_empty_session():
    r = client.post(
        "/sessions",
        json={"raw_spec": "Empty session", "selected_critics": ["assumption"]},
    )
    session_id = r.json()["id"]

    resp = client.get(f"/sessions/{session_id}/risks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_list_risks_with_filters():
    session_id, _ = _create_session_with_risks()

    # Filter by severity
    resp = client.get(f"/sessions/{session_id}/risks?severity=structural")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert all(r["severity"] == "structural" for r in data["items"])

    # Filter by status
    resp = client.get(f"/sessions/{session_id}/risks?status=open")
    assert resp.status_code == 200
    assert resp.json()["total"] == 3

    # Unknown status filter is rejected, not silently empty
    resp = client.get(f"/sessions/{session_id}/risks?status=bogus")
    assert resp.status_code == 400


def test_list_risks_pagination():
    session_id, _ = _create_session_with_risks()

    first = client.get(f"/sessions/{session_id}/risks?limit=2&offset=0").json()
    assert first["total"] == 3
    assert len(first["items"]) == 2

    second = client.get(f"/sessions/{session_id}/risks?limit=2&offset=2").json()
    assert len(second["items"]) == 1
    assert second["items"][0]["id"] not in {r["id"] for r in first["items"]}

    # Bounds are enforced
    assert client.get(f"/sessions/{session_id}/risks?limit=0").status_code == 422
    assert client.get(f"/sessions/{session_id}/risks?limit=1000").status_code == 422
    assert client.get(f"/sessions/{session_id}/risks?offset=-1").status_code == 422


def test_list_risks_sorting():
    session_id, _ = _create_session_with_risks()

    resp = client.get(f"/sessions/{session_id}/risks?sort_by=created_at&sort_dir=asc")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert resp.json()["total"] == 3
    assert [r["claim"] for r in items] == ["Test claim 0", "Test claim 1", "Test claim 2"]

    assert client.get(f"/sessions/{session_id}/risks?sort_by=bogus").status_code == 400
    assert client.get(f"/sessions/{session_id}/risks?sort_dir=sideways").status_code == 400


# ── Risk detail ────────────────────────────────────────────────────────────
def test_get_risk_detail():
    session_id, risk_ids = _create_session_with_risks()

    resp = client.get(f"/risks/{risk_ids[0]}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == risk_ids[0]
    assert "comments" in data


# ── Patch risk ─────────────────────────────────────────────────────────────
def test_patch_risk_status():
    session_id, risk_ids = _create_session_with_risks()

    resp = client.patch(
        f"/risks/{risk_ids[0]}",
        json={"status": "mitigating"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "mitigating"


def test_patch_risk_invalid_transition():
    session_id, risk_ids = _create_session_with_risks()

    # Move to deferred
    client.patch(f"/risks/{risk_ids[0]}", json={"status": "deferred"})
    # Try to move deferred -> resolved (invalid)
    resp = client.patch(f"/risks/{risk_ids[0]}", json={"status": "resolved"})
    assert resp.status_code == 400


def test_patch_risk_same_status_preserves_resolved_at():
    session_id, risk_ids = _create_session_with_risks()

    first = client.patch(f"/risks/{risk_ids[0]}", json={"status": "resolved"}).json()
    assert first["status"] == "resolved"
    resolved_at = first["resolved_at"]
    assert resolved_at is not None

    # A same-status write must not clobber the original resolution timestamp.
    second = client.patch(f"/risks/{risk_ids[0]}", json={"status": "resolved"}).json()
    assert second["resolved_at"] == resolved_at


def test_patch_risk_owner_self_and_unassign():
    token, headers = _signup("owner-assign@test.com")
    session_id, risk_ids = _create_session_with_risks(headers=headers)

    assigned = client.patch(f"/risks/{risk_ids[0]}", json={"owner_id": "self"}, headers=headers).json()
    assert assigned["owner_email"] == "owner-assign@test.com"

    unassigned = client.patch(f"/risks/{risk_ids[0]}", json={"owner_id": ""}, headers=headers).json()
    assert unassigned["owner_id"] is None

    # JSON null leaves ownership unchanged ("" is the unassign sentinel)
    reassigned = client.patch(f"/risks/{risk_ids[0]}", json={"owner_id": "self"}, headers=headers).json()
    noop = client.patch(f"/risks/{risk_ids[0]}", json={"owner_id": None}, headers=headers).json()
    assert noop["owner_id"] == reassigned["owner_id"]


def test_patch_risk_access_denied():
    token1, headers1 = _signup("owner1@test.com")
    session_id, risk_ids = _create_session_with_risks(headers=headers1)

    # Another user tries to patch
    token2, headers2 = _signup("other1@test.com")
    resp = client.patch(
        f"/risks/{risk_ids[0]}",
        json={"status": "mitigating"},
        headers=headers2,
    )
    assert resp.status_code == 403


# ── Comments ───────────────────────────────────────────────────────────────
def test_add_comment():
    session_id, risk_ids = _create_session_with_risks()

    resp = client.post(
        f"/risks/{risk_ids[0]}/comments",
        json={"body": "This is a test comment"},
    )
    assert resp.status_code == 200
    assert resp.json()["body"] == "This is a test comment"

    # Verify it shows in detail
    detail = client.get(f"/risks/{risk_ids[0]}")
    assert len(detail.json()["comments"]) == 1


def test_comment_length_validation():
    session_id, risk_ids = _create_session_with_risks()

    resp = client.post(
        f"/risks/{risk_ids[0]}/comments",
        json={"body": ""},
    )
    assert resp.status_code == 422  # Pydantic validation error


# ── Summary ────────────────────────────────────────────────────────────────
def test_risk_summary_counts():
    session_id, risk_ids = _create_session_with_risks()

    resp = client.get(f"/sessions/{session_id}/risk-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert "by_status" in data
    assert "by_severity" in data


# ── Re-evaluate ────────────────────────────────────────────────────────────
def test_re_evaluate_creates_run():
    session_id, risk_ids = _create_session_with_risks()

    resp = client.post(f"/risks/{risk_ids[0]}/re-evaluate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert "run_id" in resp.json()
