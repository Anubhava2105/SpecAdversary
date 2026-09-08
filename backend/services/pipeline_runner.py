"""Durable execution boundary for LangGraph analyses."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from core.broker import publish_event
from db.database import engine
from db.models import AnalysisRun, RunEvent, RunStatus, SessionStatus, SpecSession
from services import lifecycle
from services.graph import spec_graph
from services.lifecycle import IllegalTransition, as_utc
from services.llm_gateway import RUN_TOKEN_BUDGET, BudgetExceeded, begin_token_budget, end_token_budget
from services.risk_service import upsert_risks_from_findings

logger = logging.getLogger(__name__)
PIPELINE_TIMEOUT_SECONDS = 900
# A healthy run emits events continuously; the longest legitimate silence is
# one retry cycle (~140s). Anything quieter than this is orphaned.
RUN_STALL_SECONDS = int(os.getenv("RUN_STALL_SECONDS", "300"))
# Backstop slightly above PIPELINE_TIMEOUT_SECONDS: a run still marked
# "running" past its own in-process timeout lost its worker.
RUN_MAX_AGE_SECONDS = int(os.getenv("RUN_MAX_AGE_SECONDS", str(PIPELINE_TIMEOUT_SECONDS + 90)))


def _save(db: Session, *rows) -> None:
    """Add rows and commit — the shared tail of every transition helper."""
    for row in rows:
        db.add(row)
    db.commit()


async def emit_event(run_id: UUID, event: dict) -> None:
    """Persist an event, then fan it out to live WebSocket subscribers.

    Persistence happens first: reconnecting clients replay from RunEvent
    rows, pub/sub only accelerates delivery.
    """
    event_type = str(event.get("type", "unknown"))
    with Session(engine) as db:
        latest = db.exec(
            select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)
        ).one()
        row = RunEvent(run_id=run_id, sequence=(latest or 0) + 1, type=event_type, payload=event)
        db.add(row)
        db.commit()
        db.refresh(row)
    try:
        await publish_event(run_id, row.sequence, event)
    except Exception:
        logger.exception("Event publish failed for run %s (non-fatal)", run_id)


async def reap_stuck_runs(now: datetime | None = None) -> list[UUID]:
    """Mark orphaned runs as failed and surface a terminal WS event.

    A `running` run is stuck when its latest RunEvent (or start) is older
    than RUN_STALL_SECONDS, or when it exceeds RUN_MAX_AGE_SECONDS outright.
    A `queued` run older than RUN_MAX_AGE_SECONDS lost its worker before it
    ever started — without this its session spins in `parsing` forever.
    Without reaping, a crashed worker leaves the session spinning forever.
    """
    now = now or datetime.now(timezone.utc)
    reaped: list[UUID] = []
    terminal_events: dict[UUID, list[dict]] = {}
    reaped_codes: dict[UUID, str] = {}
    with Session(engine) as db:
        stuck = db.exec(
            select(AnalysisRun).where(
                (AnalysisRun.status == RunStatus.running) | (AnalysisRun.status == RunStatus.queued)
            )
        ).all()
        for run in stuck:
            started = as_utc(run.started_at) or as_utc(run.created_at) or now
            latest_event_at = as_utc(
                db.exec(select(func.max(RunEvent.created_at)).where(RunEvent.run_id == run.id)).one()
            )
            last_activity = max(started, latest_event_at) if latest_event_at else started
            idle_seconds = (now - last_activity).total_seconds()
            age_seconds = (now - started).total_seconds()

            stalled = run.status == RunStatus.running and idle_seconds > RUN_STALL_SECONDS
            too_old = age_seconds > RUN_MAX_AGE_SECONDS
            if not (stalled or too_old):
                continue

            code = "run_stalled" if stalled else "run_timeout"
            session = db.get(SpecSession, run.session_id)
            # The lifecycle cascade only flips in-flight sessions, so a stale
            # orphaned run reaped after its session finished can't corrupt it.
            events = lifecycle.transition_run(
                run,
                RunStatus.failed,
                cascade_session=session,
                at=now,
                error_code=code,
                error_message="Analysis interrupted. Please try again.",
            )
            _save(db, run, *( [session] if session is not None else []))

            logger.warning("Reaped %s run %s (idle=%ds age=%ds)", code, run.id, idle_seconds, age_seconds)
            reaped.append(run.id)
            terminal_events[run.id] = events
            reaped_codes[run.id] = code

    for run_id in reaped:
        # Terminal events after commit so connected and reconnecting clients see the failure.
        # The published code matches the persisted error_code (no silent translation).
        await emit_event(run_id, {"type": "error", "message": "Analysis interrupted. Please try again.", "code": reaped_codes[run_id]})
        for event in terminal_events.get(run_id, []):
            await emit_event(run_id, event)
    return reaped


def update_session(session_id: UUID, **values) -> None:
    with Session(engine) as db:
        row = db.get(SpecSession, session_id)
        if row is None:
            return
        for key, value in values.items():
            setattr(row, key, value)
        db.add(row)
        db.commit()


def _apply_session_transition(session_id: UUID, to: SessionStatus, **values) -> list[dict]:
    """Load a session, move it through the lifecycle, commit.

    Illegal moves are logged and skipped rather than crashing the run — the
    stream may legitimately deliver duplicate or late status events.
    """
    with Session(engine) as db:
        row = db.get(SpecSession, session_id)
        if row is None:
            return []
        try:
            events = lifecycle.transition_session(row, to, **values)
        except lifecycle.IllegalTransition:
            logger.warning("Skipped illegal session %s transition to %s", session_id, to.value)
            return []
        _save(db, row)
        return events


def _apply_run_transition(run_id: UUID, to: RunStatus, cascade: bool = False, at=None, **values) -> list[dict]:
    """Load a run, move it through the lifecycle, commit; optionally cascade
    failure into its session (see lifecycle.transition_run)."""
    with Session(engine) as db:
        run = db.get(AnalysisRun, run_id)
        if run is None:
            return []
        cascade_session = db.get(SpecSession, run.session_id) if cascade else None
        events = lifecycle.transition_run(run, to, cascade_session=cascade_session, at=at, **values)
        _save(db, run, *( [cascade_session] if cascade_session is not None else []))
        return events


async def execute_run(run_id: UUID) -> None:
    """Execute exactly one queued run; safe to invoke from a separate worker."""
    with Session(engine) as db:
        run = db.get(AnalysisRun, run_id)
        if run is None or run.status != RunStatus.queued:
            return
        session = db.get(SpecSession, run.session_id)
        if session is None:
            lifecycle.transition_run(run, RunStatus.failed, error_code="session_missing")
            db.add(run)
            db.commit()
            return
        lifecycle.transition_run(run, RunStatus.running)
        run.attempt += 1
        try:
            lifecycle.transition_session(session, SessionStatus.parsing)
        except IllegalTransition:
            # Another run already owns this session (concurrent dispatch):
            # don't hijack it — fail this run and stop.
            run_id = run.id
            lifecycle.transition_run(
                run, RunStatus.failed, error_code="session_busy",
                error_message="Session is already being analyzed by another run.",
            )
            _save(db, run)
            session_busy = True
        else:
            _save(db, run, session)
            session_id = session.id
            run_id = run.id
            session_busy = False
            raw_spec = session.raw_spec
            selected_critics = session.selected_critics
            finding_id = run.re_evaluate_finding_id
            existing_findings = session.findings
            parsed_sections = session.parsed_sections

    if session_busy:
        await emit_event(run_id, {"type": "error", "message": "Session is already being analyzed by another run.", "code": "session_busy"})
        return

    await emit_event(run_id, {"type": "status", "status": SessionStatus.parsing.value})
    final: dict = {}
    begin_token_budget()
    try:
        initial_state: dict[str, Any] = {"raw_spec": raw_spec, "findings": []}
        if selected_critics:
            initial_state["selected_critics"] = selected_critics
        if finding_id:
            initial_state.update({
                "existing_findings": existing_findings,
                "parsed_sections": parsed_sections,
                "re_evaluate_finding_id": finding_id,
            })

        async def stream() -> None:
            async for mode, data in spec_graph.astream(initial_state, stream_mode=["custom", "updates"]):
                if mode == "custom" and isinstance(data, dict):
                    await emit_event(run_id, data)
                    if data.get("type") == "status":
                        try:
                            next_status = lifecycle.ingest_status(data.get("status"))
                        except ValueError:
                            logger.warning("Ignoring unknown pipeline status event: %r", data.get("status"))
                        else:
                            _apply_session_transition(session_id, next_status)
                elif mode == "updates" and isinstance(data, dict):
                    for node, update in data.items():
                        if not isinstance(update, dict):
                            continue
                        for key, value in update.items():
                            if key == "findings" and isinstance(value, list):
                                if node in ("re_evaluate", "synthesizer"):
                                    # These nodes return the complete list, not
                                    # a delta — replacing avoids double-counting
                                    # (accumulated critic rows + the full list).
                                    final["findings"] = list(value)
                                else:
                                    final.setdefault("findings", []).extend(value)
                            else:
                                final[key] = value
                        persisted = {key: update[key] for key in ("parsed_sections", "missing_context") if key in update}
                        if "findings" in update:
                            persisted["findings"] = final["findings"]
                        if "moderated_findings" in update:
                            persisted["findings"] = update["moderated_findings"]
                        if persisted:
                            update_session(session_id, **persisted)

        await asyncio.wait_for(stream(), timeout=PIPELINE_TIMEOUT_SECONDS)
        revised_spec = final.get("revised_spec", raw_spec)
        findings = final.get("moderated_findings", final.get("findings", []))
        done_events = _apply_session_transition(session_id, SessionStatus.done, findings=findings, revised_spec=revised_spec)
        if not done_events and _session_terminal_state(session_id):
            # The session moved to `failed` while this run was working (e.g.
            # the reaper collected a stale view): reporting success would leave
            # a succeeded run attached to a failed session. Fail honestly.
            await _fail_run(run_id, "state_conflict", "Analysis failed. Please try again.")
            return
        # Upsert normalized risk rows from the final findings
        try:
            upsert_risks_from_findings(session_id, findings, run_id)
        except Exception:
            logger.exception("Risk upsert failed for run %s (non-fatal)", run_id)
        _apply_run_transition(run_id, RunStatus.succeeded)
        await emit_event(run_id, {"type": "done", "revised_spec": revised_spec})
    except BudgetExceeded as exc:
        logger.warning("Run %s stopped: %s", run_id, exc)
        await _fail_run(run_id, "budget_exceeded", "Analysis exceeded its processing budget. Please try again.")
    except asyncio.CancelledError:
        _apply_run_transition(run_id, RunStatus.cancelled)
        await emit_event(run_id, {"type": "error", "message": "Analysis cancelled.", "code": "cancelled"})
        raise
    except Exception:
        logger.exception("Pipeline failed for run %s", run_id)
        await _fail_run(run_id, "pipeline_failed", "Analysis failed. Please try again.")
    finally:
        used = end_token_budget()
        if used:
            logger.info("run=%s token_usage=%d budget_limit=%d", run_id, used, RUN_TOKEN_BUDGET)


def _session_terminal_state(session_id: UUID) -> bool:
    """True when the session is no longer acceptably completable (failed)."""
    with Session(engine) as db:
        row = db.get(SpecSession, session_id)
        return row is not None and row.status == SessionStatus.failed


async def _fail_run(run_id: UUID, code: str, message: str) -> None:
    """Fail a run mid-flight: transition (cascading to an in-flight session),
    then surface the error and resulting status events on the stream."""
    events = _apply_run_transition(
        run_id,
        RunStatus.failed,
        cascade=True,
        error_code=code,
        error_message=message,
    )
    await emit_event(run_id, {"type": "error", "message": message, "code": code})
    for event in events:
        await emit_event(run_id, event)
