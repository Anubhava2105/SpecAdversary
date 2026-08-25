"""Tests for session input validation and terminal-state guards."""
import asyncio
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import Session

import main
from database import engine
from models import Risk, SessionStatus, SpecSession

main.dispatch_run = lambda run_id: asyncio.sleep(0)
client = TestClient(main.app)


def _make_session(status: SessionStatus) -> str:
    with Session(engine) as db:
        row = SpecSession(raw_spec="spec text", status=status, findings=[
            {"id": "f1", "critic": "assumption", "severity": "minor", "claim": "c", "critique": "x"},
        ])
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)


def test_empty_selected_critics_rejected():
    r = client.post("/sessions", json={"raw_spec": "spec", "selected_critics": []})
    assert r.status_code == 422


def test_unknown_critic_value_rejected():
    r = client.post("/sessions", json={"raw_spec": "spec", "selected_critics": ["tarot"]})
    assert r.status_code == 422


def test_valid_critics_accepted():
    r = client.post("/sessions", json={"raw_spec": "spec text", "selected_critics": ["assumption"]})
    assert r.status_code == 200


def test_reply_rejected_while_analysis_in_progress():
    sid = _make_session(SessionStatus.critiquing)
    r = client.post(f"/sessions/{sid}/findings/f1/reply", json={"reply": "why?"})
    assert r.status_code == 409


def test_reply_allowed_on_done_session():
    sid = _make_session(SessionStatus.done)
    r = client.post(f"/sessions/{sid}/findings/f1/reply", json={"reply": "why?"})
    assert r.status_code == 200
    assert r.json()["status"] == "queued"


def test_reevaluate_rejected_while_analysis_in_progress():
    sid = _make_session(SessionStatus.synthesizing)
    with Session(engine) as db:
        row = db.get(SpecSession, UUID(sid))
        risk = Risk(session_id=row.id, finding_id="f1", critic="assumption")
        db.add(risk)
        db.commit()
        db.refresh(risk)
        rid = str(risk.id)

    r = client.post(f"/risks/{rid}/re-evaluate")
    assert r.status_code == 409
