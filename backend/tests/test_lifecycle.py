"""Exhaustive contract tests for the session-and-run lifecycle module.

The lifecycle is the single owner of legal status movement. These tests drive
it through its interface with plain ORM objects — no database, no engine.
"""
import uuid

import pytest

from db.models import AnalysisRun, RunStatus, SessionStatus
from services.lifecycle import (
    IllegalTransition,
    accepts_client_activity,
    ingest_status,
    transition_run,
    transition_session,
)


def _session(status):
    from db.models import SpecSession

    return SpecSession(id=uuid.uuid4(), raw_spec="spec", status=status)


def make_run(status=RunStatus.queued):
    return AnalysisRun(session_id=uuid.uuid4(), status=status)


# ── The approved legality table ────────────────────────────────────────────
IN_FLIGHT = [SessionStatus.parsing, SessionStatus.critiquing, SessionStatus.moderating, SessionStatus.synthesizing]
ALL = IN_FLIGHT + [SessionStatus.done, SessionStatus.failed]

FORWARD = {
    SessionStatus.parsing: [SessionStatus.critiquing],
    SessionStatus.critiquing: [SessionStatus.moderating],
    SessionStatus.moderating: [SessionStatus.synthesizing],
    SessionStatus.synthesizing: [SessionStatus.done],
}


@pytest.mark.parametrize("frm", ALL)
@pytest.mark.parametrize("to", ALL)
def test_session_transition_table(frm, to):
    """Every (from, to) pair is either explicitly legal or must raise."""
    session = _session(frm)

    legal = frm == to  # idempotent writes are always legal
    legal |= to == SessionStatus.failed  # any state can fail
    legal |= to in FORWARD.get(frm, [])  # forward stage progression
    legal |= to == SessionStatus.done and frm in IN_FLIGHT  # completion from whichever stage the run reached
    legal |= frm in (SessionStatus.done, SessionStatus.failed) and to == SessionStatus.parsing  # re-evaluate / retry

    if legal:
        events = transition_session(session, to)
        assert session.status == to
        for event in events:
            assert event["type"] == "status"
            assert event["status"] == to.value
    else:
        with pytest.raises(IllegalTransition):
            transition_session(session, to)
        # A rejected transition must not have mutated anything.
        assert session.status == frm


def test_transition_session_returns_status_events_only():
    session = _session(SessionStatus.synthesizing)
    events = transition_session(session, SessionStatus.done, revised_spec="hardened")
    assert events == [{"type": "status", "status": "done"}]
    assert session.revised_spec == "hardened"  # extra fields still applied


def test_transition_run_sets_started_at_when_running():
    run = make_run()
    assert run.started_at is None
    transition_run(run, RunStatus.running)
    assert run.started_at is not None
    assert run.status == RunStatus.running


@pytest.mark.parametrize("terminal", [RunStatus.succeeded, RunStatus.failed, RunStatus.cancelled])
def test_transition_run_sets_finished_at_on_terminal(terminal):
    run = make_run(RunStatus.running)
    transition_run(run, terminal)
    assert run.finished_at is not None


# ── Run legality table (hardcoded expectations, not derived from the impl) ──
RUN_LEGAL = {
    (RunStatus.queued, RunStatus.running),
    (RunStatus.queued, RunStatus.failed),  # fail-fast before start (missing session)
    (RunStatus.queued, RunStatus.cancelled),
    (RunStatus.running, RunStatus.succeeded),
    (RunStatus.running, RunStatus.failed),
    (RunStatus.running, RunStatus.cancelled),
}

ALL_RUNS = [RunStatus.queued, RunStatus.running, RunStatus.succeeded, RunStatus.failed, RunStatus.cancelled]


@pytest.mark.parametrize("frm", ALL_RUNS)
@pytest.mark.parametrize("to", ALL_RUNS)
def test_run_transition_table(frm, to):
    """Every (from, to) run pair is either explicitly legal or must raise."""
    run = make_run(frm)
    legal = frm == to or (frm, to) in RUN_LEGAL  # idempotent writes are always legal
    if legal:
        transition_run(run, to)
        assert run.status == to
    else:
        with pytest.raises(IllegalTransition):
            transition_run(run, to)
        assert run.status == frm  # rejected transition mutates nothing


def test_illegal_run_transition_sets_no_timestamps():
    run = make_run(RunStatus.succeeded)
    assert run.finished_at is None
    with pytest.raises(IllegalTransition):
        transition_run(run, RunStatus.running)  # resurrection is illegal
    assert run.status == RunStatus.succeeded
    assert run.started_at is None and run.finished_at is None


# ── Cascade rule: run failure flips the session only while it's in flight ──
@pytest.mark.parametrize("session_status", IN_FLIGHT)
def test_failed_run_cascades_to_in_flight_session(session_status):
    run = make_run()
    session = _session(session_status)
    transition_run(run, RunStatus.failed, cascade_session=session)
    assert run.status == RunStatus.failed
    assert session.status == SessionStatus.failed
    assert run.finished_at is not None


@pytest.mark.parametrize("session_status", [SessionStatus.done, SessionStatus.failed])
def test_failed_run_does_not_cascade_to_terminal_session(session_status):
    """A stale orphaned run reaped late must not corrupt a finished session."""
    run = make_run()
    session = _session(session_status)
    events = transition_run(run, RunStatus.failed, cascade_session=session)
    assert run.status == RunStatus.failed
    assert session.status == session_status  # untouched
    assert events == []  # nothing changed, so nothing to announce


def test_successful_run_does_not_cascade():
    run = make_run(RunStatus.running)
    session = _session(SessionStatus.synthesizing)
    events = transition_run(run, RunStatus.succeeded, cascade_session=session)
    assert session.status == SessionStatus.synthesizing  # success path sets `done` explicitly itself
    assert events == []  # success cascades nothing


def test_transition_run_honours_injected_clock():
    from datetime import datetime, timezone

    stamp = datetime(2026, 8, 25, tzinfo=timezone.utc)
    run = make_run(RunStatus.running)
    run.started_at = stamp
    transition_run(run, RunStatus.failed, at=stamp)
    assert run.finished_at == stamp


# ── Ingestion of raw graph-emitted strings ────────────────────────────────
@pytest.mark.parametrize("raw", ["parsing", "critiquing", "moderating", "synthesizing", "done", "failed"])
def test_ingest_status_accepts_known_names(raw):
    assert ingest_status(raw) == SessionStatus(raw)


@pytest.mark.parametrize("raw", ["critiquing ", "", "running", "PARSING", None])
def test_ingest_status_rejects_unknown_names(raw):
    with pytest.raises(ValueError):
        ingest_status(raw)


# ── The client-activity predicate ─────────────────────────────────────────
@pytest.mark.parametrize("status", IN_FLIGHT)
def test_in_flight_sessions_reject_client_activity(status):
    assert accepts_client_activity(status) is False


@pytest.mark.parametrize("status", [SessionStatus.done, SessionStatus.failed])
def test_terminal_sessions_accept_client_activity(status):
    assert accepts_client_activity(status) is True
