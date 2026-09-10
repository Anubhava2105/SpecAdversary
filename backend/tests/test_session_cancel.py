"""Tests for POST /sessions/{sid}/cancel: user-initiated run cancellation."""
import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import pytest

import routes.session_routes as session_routes
from core import deps
from core.deps import dispatch_run as _real_dispatch
from db.database import engine
from db.models import AnalysisRun, RunStatus, SessionStatus, SpecSession, User
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """Event publishing is non-fatal; never touch real Redis from tests."""
    from services import pipeline_runner

    async def _noop(run_id, sequence, event):
        return None

    monkeypatch.setattr(pipeline_runner, "publish_event", _noop)


def _make_session_with_run(run_status=RunStatus.queued, user=None) -> tuple:
    session = SpecSession(raw_spec="cancel me", user_id=user.id if user else None)
    run = AnalysisRun(session_id=session.id, status=run_status)
    with Session(engine) as db:
        db.add(session)
        db.add(run)
        db.commit()
        return session.id, run.id


def _get_run(run_id) -> AnalysisRun:
    with Session(engine) as db:
        row = db.get(AnalysisRun, run_id)
        db.expunge(row)
        return row


def _get_session(session_id) -> SpecSession:
    with Session(engine) as db:
        row = db.get(SpecSession, session_id)
        db.expunge(row)
        return row


def _make_user(email: str) -> tuple[User, dict]:
    r = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    with Session(engine) as db:
        user = db.exec(select(User).where(User.email == email)).first()
        db.expunge(user)
    return user, {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_cancel_queued_run_marks_cancelled_and_fails_session(monkeypatch):
    async def _no_abort(run_id: str) -> bool:
        return False

    monkeypatch.setattr(session_routes, "abort_arq_job", _no_abort)
    sid, rid = _make_session_with_run(RunStatus.queued)
    r = client.post(f"/sessions/{sid}/cancel")
    assert r.status_code == 200
    assert r.json() == {"status": "cancelled", "run_id": str(rid)}
    assert _get_run(rid).status == RunStatus.cancelled
    assert _get_run(rid).error_code == "cancelled_by_user"
    assert _get_session(sid).status == SessionStatus.failed


def test_cancel_running_run(monkeypatch):
    async def _no_abort(run_id: str) -> bool:
        return True

    monkeypatch.setattr(session_routes, "abort_arq_job", _no_abort)
    sid, rid = _make_session_with_run(RunStatus.running)
    r = client.post(f"/sessions/{sid}/cancel")
    assert r.json()["status"] == "cancelled"
    assert _get_run(rid).status == RunStatus.cancelled


def test_cancel_with_no_runs_is_noop():
    with Session(engine) as db:
        row = SpecSession(raw_spec="nothing running")
        db.add(row)
        db.commit()
        sid = row.id
    r = client.post(f"/sessions/{sid}/cancel")
    assert r.status_code == 200
    assert r.json() == {"status": "noop", "run_id": None}


def test_cancel_terminal_run_is_noop():
    sid, rid = _make_session_with_run(RunStatus.succeeded)
    r = client.post(f"/sessions/{sid}/cancel")
    assert r.json() == {"status": "noop", "run_id": None}
    assert _get_run(rid).status == RunStatus.succeeded


def test_cancel_unknown_session_404():
    assert client.post(f"/sessions/{UUID(int=0)}/cancel").status_code == 404


def test_cancel_other_users_session_403():
    _, headers_a = _make_user("cancel-owner@example.com")
    _, headers_b = _make_user("cancel-stranger@example.com")
    with Session(engine) as db:
        owner = db.exec(select(User).where(User.email == "cancel-owner@example.com")).first()
        row = SpecSession(raw_spec="mine", user_id=owner.id)
        run = AnalysisRun(session_id=row.id)
        db.add(row)
        db.add(run)
        db.commit()
        sid = row.id
    assert client.post(f"/sessions/{sid}/cancel", headers=headers_b).status_code == 403
    assert client.post(f"/sessions/{sid}/cancel", headers=headers_a).json()["status"] == "cancelled"


def test_cancel_stops_inline_task(monkeypatch):
    monkeypatch.setenv("INLINE_WORKER", "true")
    started = asyncio.Event()
    release = asyncio.Event()

    async def _never_ends(run_id):
        started.set()
        await release.wait()

    monkeypatch.setattr(deps, "execute_run", _never_ends)
    sid, rid = _make_session_with_run(RunStatus.queued)

    async def _run():
        await _real_dispatch(rid)
        await asyncio.wait_for(started.wait(), timeout=5)
        tasks = [t for t in list(deps.inline_tasks) if getattr(t, "run_id", None) == rid]
        assert len(tasks) == 1
        r = client.post(f"/sessions/{sid}/cancel")
        assert r.json()["status"] == "cancelled"
        # The stop signal crosses threads; give the loop a few ticks to
        # deliver the cancellation to the inline task.
        for _ in range(100):
            if tasks[0].cancelled() or tasks[0].done():
                break
            await asyncio.sleep(0.01)
        assert tasks[0].cancelled() or tasks[0].done()
        release.set()

    asyncio.run(_run())
    assert _get_run(rid).status == RunStatus.cancelled
