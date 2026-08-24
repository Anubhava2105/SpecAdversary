"""Tests for the stuck-run reaper."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlmodel import Session, select

import pipeline_runner
from database import engine
from models import AnalysisRun, RunEvent, RunStatus, SessionStatus, SpecSession
import asyncio

from pipeline_runner import reap_stuck_runs


def _make_run(
    *,
    status: RunStatus = RunStatus.running,
    started_delta: float | None = None,
    last_event_delta: float | None = None,
) -> tuple[str, str]:
    """Create a run (and its session row); return (run_id, session_id).

    IDs are captured while the rows are attached — ORM instances are expired
    once their Session closes and cannot be read afterwards.
    """
    with Session(engine) as db:
        session_row = SpecSession(raw_spec="spec")
        db.add(session_row)
        db.commit()
        db.refresh(session_row)

        run = AnalysisRun(session_id=session_row.id, status=status)
        if started_delta is not None:
            run.started_at = datetime.now(timezone.utc) - timedelta(seconds=started_delta)
        db.add(run)
        db.commit()
        db.refresh(run)

        if last_event_delta is not None:
            event = RunEvent(
                run_id=run.id,
                sequence=1,
                type="status",
                payload={"type": "status", "status": "parsing"},
                created_at=datetime.now(timezone.utc) - timedelta(seconds=last_event_delta),
            )
            db.add(event)
            db.commit()

        return str(run.id), str(session_row.id)


def _get_run(run_id) -> AnalysisRun:
    with Session(engine) as db:
        return db.get(AnalysisRun, UUID(run_id))


def test_recent_active_run_is_untouched():
    run_id, _ = _make_run(last_event_delta=30)
    assert asyncio.run(reap_stuck_runs()) == []
    assert _get_run(run_id).status == RunStatus.running


def test_idle_run_reaped_after_stall_threshold():
    # Event silence (400s) exceeds RUN_STALL_SECONDS even though run is young.
    run_id, session_id = _make_run(started_delta=420, last_event_delta=400)
    reaped = asyncio.run(reap_stuck_runs())
    assert UUID(run_id) in reaped
    row = _get_run(run_id)
    assert row.status == RunStatus.failed
    assert row.error_code == "run_stalled"
    with Session(engine) as db:
        assert db.get(SpecSession, UUID(session_id)).status == SessionStatus.failed
        events = db.exec(select(RunEvent).where(RunEvent.run_id == UUID(run_id))).all()
        types = [e.type for e in events]
        assert "error" in types and "status" in types


def test_old_run_reaped_by_age_backstop_despite_fresh_events():
    # A pathological run keeps emitting events but never finishes; the age
    # backstop must still collect it.
    run_id, _ = _make_run(
        started_delta=pipeline_runner.RUN_MAX_AGE_SECONDS + 60,
        last_event_delta=10,
    )
    reaped = asyncio.run(reap_stuck_runs())
    assert UUID(run_id) in reaped
    assert _get_run(run_id).error_code == "run_timeout"


def test_queued_and_terminal_runs_untouched():
    queued_id, _ = _make_run(status=RunStatus.queued, started_delta=5000)
    done_id, _ = _make_run(status=RunStatus.succeeded, started_delta=5000)
    assert asyncio.run(reap_stuck_runs()) == []
    assert _get_run(queued_id).status == RunStatus.queued
    assert _get_run(done_id).status == RunStatus.succeeded


def test_reaper_is_idempotent():
    run_id, _ = _make_run(started_delta=2000)
    first = asyncio.run(reap_stuck_runs())
    second = asyncio.run(reap_stuck_runs())
    assert UUID(run_id) in first and second == []
