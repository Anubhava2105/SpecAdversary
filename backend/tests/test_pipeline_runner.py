"""Tests for pipeline_runner.execute_run: success, failure, and timeout paths.

The LangGraph pipeline is replaced with a fake astream so these tests exercise
the durable-execution boundary (state transitions, event persistence, risk
upsert) without any LLM or Redis dependency.
"""
import asyncio
from typing import TypeVar
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from db.models import AnalysisRun, Risk, RunEvent, RunStatus, SessionStatus, SpecSession
from services import pipeline_runner


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """publish_event is non-fatal but would block on connection timeouts."""
    async def _noop(run_id, sequence, event):
        return None

    monkeypatch.setattr(pipeline_runner, "publish_event", _noop)


def make_session_and_run(raw_spec="Build a to-do app for cats"):
    session = SpecSession(raw_spec=raw_spec)
    run = AnalysisRun(session_id=session.id)
    with Session(pipeline_runner.engine) as db:
        db.add(session)
        db.add(run)
        db.commit()
        return session.id, run.id  # read PKs before the commit-expired objects detach


class FakeGraph:
    """Stands in for spec_graph; `behaviour` is an async generator factory."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    def astream(self, initial_state, stream_mode=None):
        self.calls.append(initial_state)
        return self.behaviour(initial_state)


def _yield(*updates):
    """Return an async-generator factory emitting each update dict as an 'updates' frame."""
    async def gen(_state):
        for update in updates:
            yield "updates", {uuid4().hex: update}
    return gen


def _yield_named(*named_updates):
    """Like _yield but with explicit (node_name, update) pairs."""
    async def gen(_state):
        for node, update in named_updates:
            yield "updates", {node: update}
    return gen


_T = TypeVar("_T")


def _get_detached(db: Session, model: type[_T], key) -> _T:
    """Load an entity and detach it so its loaded state survives session close."""
    row = db.get(model, key)
    assert row is not None
    db.expunge(row)
    return row


def get_run(run_id) -> AnalysisRun:
    with Session(pipeline_runner.engine) as db:
        return _get_detached(db, AnalysisRun, run_id)


def get_session(session_id) -> SpecSession:
    with Session(pipeline_runner.engine) as db:
        return _get_detached(db, SpecSession, session_id)


def test_execute_run_success_persists_findings_and_risks(monkeypatch):
    finding = {
        "id": "F1",
        "critic": "assumption",
        "severity": "structural",
        "claim": "cat owners want this",
        "critique": "unvalidated",
        "suggested_fix": "interview 5 owners",
    }
    graph = FakeGraph(_yield({"findings": [finding]}, {"revised_spec": "Better spec"}))
    monkeypatch.setattr(pipeline_runner, "spec_graph", graph)

    session_id, run_id = make_session_and_run()
    asyncio.run(pipeline_runner.execute_run(run_id))

    run = get_run(run_id)
    assert run.status == RunStatus.succeeded
    assert run.started_at is not None
    assert run.finished_at is not None

    session = get_session(session_id)
    assert session.status == SessionStatus.done
    assert session.findings == [finding]
    assert session.revised_spec == "Better spec"

    # Findings are normalized into the Risk Register.
    with Session(pipeline_runner.engine) as db:
        risks = db.exec(select(Risk).where(Risk.session_id == session_id)).all()
        assert len(risks) == 1
        risk = risks[0]
        db.expunge(risk)
    assert risk.finding_id == "F1"
    assert risk.source_run_id == run_id

    # Terminal done-event was persisted for replay.
    with Session(pipeline_runner.engine) as db:
        events = db.exec(select(RunEvent).where(RunEvent.run_id == run_id)).all()
        event_types = {e.type for e in events}
    assert "done" in event_types


def test_execute_run_failure_marks_session_and_run_failed(monkeypatch):
    async def explode(state):
        raise RuntimeError("LLM exploded")

        yield  # pragma: no cover — makes the factory an async generator

    graph = FakeGraph(explode)
    monkeypatch.setattr(pipeline_runner, "spec_graph", graph)

    session_id, run_id = make_session_and_run()
    asyncio.run(pipeline_runner.execute_run(run_id))

    run = get_run(run_id)
    assert run.status == RunStatus.failed
    assert run.error_code == "pipeline_failed"
    assert get_session(session_id).status == SessionStatus.failed

    with Session(pipeline_runner.engine) as db:
        events = db.exec(select(RunEvent).where(RunEvent.run_id == run_id)).all()
        error_codes = {e.payload.get("code") for e in events if e.type == "error"}
    assert "pipeline_failed" in error_codes


def test_execute_run_timeout_fails_the_run(monkeypatch):
    async def hang_forever(state):
        await asyncio.sleep(3600)
        yield  # pragma: no cover

    graph = FakeGraph(hang_forever)
    monkeypatch.setattr(pipeline_runner, "spec_graph", graph)
    monkeypatch.setattr(pipeline_runner, "PIPELINE_TIMEOUT_SECONDS", 0.05)

    session_id, run_id = make_session_and_run()
    asyncio.run(pipeline_runner.execute_run(run_id))

    run = get_run(run_id)
    assert run.status == RunStatus.failed
    assert run.error_code == "pipeline_failed"
    assert run.finished_at is not None
    assert get_session(session_id).status == SessionStatus.failed


def test_execute_run_ignores_non_queued_runs():
    session_id, run_id = make_session_and_run()
    with Session(pipeline_runner.engine) as db:
        row = db.get(AnalysisRun, run_id)
        assert row is not None
        row.status = RunStatus.running
        db.add(row)
        db.commit()

    asyncio.run(pipeline_runner.execute_run(run_id))

    run = get_run(run_id)
    assert run.status == RunStatus.running
    assert run.attempt == 0


def test_execute_run_missing_session_fails_fast():
    orphan_run = AnalysisRun(session_id=uuid4())
    with Session(pipeline_runner.engine) as db:
        db.add(orphan_run)
        db.commit()
        orphan_id = orphan_run.id

    asyncio.run(pipeline_runner.execute_run(orphan_id))

    run = get_run(orphan_run.id)
    assert run.status == RunStatus.failed
    assert run.error_code == "session_missing"


def test_execute_run_does_not_double_count_full_list_updates(monkeypatch):
    """Nodes returning complete finding lists (re-evaluate/synthesizer) replace,
    they must not append onto already-accumulated critic rows."""
    critic_finding = {
        "id": "C1", "critic": "assumption", "severity": "minor",
        "claim": "c", "critique": "x", "suggested_fix": "f",
    }
    full_list = [
        {**critic_finding, "id": "C1"},
        {"id": "C2", "critic": "assumption", "severity": "minor", "claim": "c2", "critique": "x2", "suggested_fix": "f2"},
    ]
    graph = FakeGraph(_yield_named(
        ("assumption_hunter", {"findings": [critic_finding]}),
        ("synthesizer", {"findings": full_list, "revised_spec": "R"}),
    ))
    monkeypatch.setattr(pipeline_runner, "spec_graph", graph)

    session_id, run_id = make_session_and_run()
    asyncio.run(pipeline_runner.execute_run(run_id))

    session = get_session(session_id)
    assert [f["id"] for f in session.findings] == ["C1", "C2"]


def test_execute_run_budget_exceeded_fails_cleanly(monkeypatch):
    from services.llm_gateway import BudgetExceeded

    async def over_budget(state):
        raise BudgetExceeded("Run token budget exhausted (1/1)")
        yield  # pragma: no cover

    monkeypatch.setattr(pipeline_runner, "spec_graph", FakeGraph(over_budget))

    session_id, run_id = make_session_and_run()
    asyncio.run(pipeline_runner.execute_run(run_id))

    run = get_run(run_id)
    assert run.status == RunStatus.failed
    assert run.error_code == "budget_exceeded"
    assert get_session(session_id).status == SessionStatus.failed


def test_execute_run_refuses_to_hijack_in_flight_session(monkeypatch):
    graph = FakeGraph(_yield({"revised_spec": "R"}))
    monkeypatch.setattr(pipeline_runner, "spec_graph", graph)

    session_id, run_id = make_session_and_run()
    with Session(pipeline_runner.engine) as db:
        row = db.get(SpecSession, session_id)
        assert row is not None
        row.status = SessionStatus.critiquing  # owned by another run
        db.add(row)
        db.commit()

    asyncio.run(pipeline_runner.execute_run(run_id))

    run = get_run(run_id)
    assert run.status == RunStatus.failed
    assert run.error_code == "session_busy"
    assert graph.calls == []  # graph never ran
    assert get_session(session_id).status == SessionStatus.critiquing  # untouched


def test_execute_run_marks_state_conflict_when_session_failed_mid_run(monkeypatch):
    """If the session failed while the run was working, success must not be reported."""
    async def gen(_state):
        yield "updates", {"synthesizer": {"revised_spec": "R"}}
        # Simulate the reaper failing the session mid-stream.
        with Session(pipeline_runner.engine) as db:
            row = db.get(SpecSession, session_id)
            assert row is not None
            row.status = SessionStatus.failed
            db.add(row)
            db.commit()

    monkeypatch.setattr(pipeline_runner, "spec_graph", FakeGraph(gen))

    session_id, run_id = make_session_and_run()
    asyncio.run(pipeline_runner.execute_run(run_id))

    run = get_run(run_id)
    assert run.status == RunStatus.failed
    assert run.error_code == "state_conflict"
    assert get_session(session_id).status == SessionStatus.failed

