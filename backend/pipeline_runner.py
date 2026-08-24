"""Durable execution boundary for LangGraph analysis jobs."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from broker import publish_event
from database import engine
from graph import spec_graph
from models import AnalysisRun, RunEvent, RunStatus, SessionStatus, SpecSession
from risk_service import upsert_risks_from_findings

logger = logging.getLogger(__name__)
PIPELINE_TIMEOUT_SECONDS = 900
# A healthy run emits events continuously; the longest legitimate silence is
# one retry cycle (~140s). Anything quieter than this is orphaned.
RUN_STALL_SECONDS = int(os.getenv("RUN_STALL_SECONDS", "300"))
# Backstop slightly above PIPELINE_TIMEOUT_SECONDS: a run still marked
# "running" past its own in-process timeout lost its worker.
RUN_MAX_AGE_SECONDS = int(os.getenv("RUN_MAX_AGE_SECONDS", str(PIPELINE_TIMEOUT_SECONDS + 90)))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


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
    """Mark orphaned `running` runs as failed and surface a terminal WS event.

    A run is stuck when its latest RunEvent (or start) is older than
    RUN_STALL_SECONDS, or when it exceeds RUN_MAX_AGE_SECONDS outright.
    Without this, a crashed worker leaves the session spinning forever.
    """
    now = now or datetime.now(timezone.utc)
    reaped: list[UUID] = []
    with Session(engine) as db:
        running = db.exec(select(AnalysisRun).where(AnalysisRun.status == RunStatus.running)).all()
        for run in running:
            started = _as_utc(run.started_at) or _as_utc(run.created_at)
            latest_event_at = _as_utc(
                db.exec(select(func.max(RunEvent.created_at)).where(RunEvent.run_id == run.id)).one()
            )
            last_activity = max(started, latest_event_at) if latest_event_at else started
            idle_seconds = (now - last_activity).total_seconds()
            age_seconds = (now - started).total_seconds()

            stalled = idle_seconds > RUN_STALL_SECONDS
            too_old = age_seconds > RUN_MAX_AGE_SECONDS
            if not (stalled or too_old):
                continue

            code = "run_stalled" if stalled else "run_timeout"
            run.status = RunStatus.failed
            run.error_code = code
            run.error_message = "Analysis interrupted. Please try again."
            run.finished_at = now
            db.add(run)

            session = db.get(SpecSession, run.session_id)
            if session is not None:
                session.status = SessionStatus.failed
                db.add(session)

            logger.warning("Reaped %s run %s (idle=%ds age=%ds)", code, run.id, idle_seconds, age_seconds)
            reaped.append(run.id)
        db.commit()

    for run_id in reaped:
        # Terminal events after commit so connected and reconnecting clients see the failure.
        await emit_event(run_id, {"type": "error", "message": "Analysis interrupted. Please try again.", "code": "run_interrupted"})
        await emit_event(run_id, {"type": "status", "status": SessionStatus.failed.value})
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


def update_run(run_id: UUID, **values) -> None:
    with Session(engine) as db:
        row = db.get(AnalysisRun, run_id)
        if row is None:
            return
        for key, value in values.items():
            setattr(row, key, value)
        db.add(row)
        db.commit()


async def execute_run(run_id: UUID) -> None:
    """Execute exactly one queued run; safe to invoke from a separate worker."""
    with Session(engine) as db:
        run = db.get(AnalysisRun, run_id)
        if run is None or run.status != RunStatus.queued:
            return
        session = db.get(SpecSession, run.session_id)
        if session is None:
            run.status = RunStatus.failed
            run.error_code = "session_missing"
            run.finished_at = datetime.now(timezone.utc)
            db.add(run)
            db.commit()
            return
        run.status = RunStatus.running
        run.attempt += 1
        run.started_at = datetime.now(timezone.utc)
        session.status = SessionStatus.parsing
        db.add(run)
        db.add(session)
        db.commit()
        session_id = session.id
        raw_spec = session.raw_spec
        selected_critics = session.selected_critics
        finding_id = run.re_evaluate_finding_id
        existing_findings = session.findings
        parsed_sections = session.parsed_sections

    await emit_event(run_id, {"type": "status", "status": SessionStatus.parsing.value})
    final: dict = {}
    try:
        initial_state = {"raw_spec": raw_spec, "findings": []}
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
                    if data.get("type") == "status" and data.get("status") in SessionStatus._value2member_map_:
                        update_session(session_id, status=SessionStatus(data["status"]))
                elif mode == "updates" and isinstance(data, dict):
                    for update in data.values():
                        if not isinstance(update, dict):
                            continue
                        for key, value in update.items():
                            if key == "findings" and isinstance(value, list):
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
        update_session(session_id, findings=findings, revised_spec=revised_spec, status=SessionStatus.done)
        # Upsert normalized risk rows from the final findings
        try:
            upsert_risks_from_findings(session_id, findings, run_id)
        except Exception:
            logger.exception("Risk upsert failed for run %s (non-fatal)", run_id)
        update_run(run_id, status=RunStatus.succeeded, finished_at=datetime.now(timezone.utc))
        await emit_event(run_id, {"type": "done", "revised_spec": revised_spec})
    except asyncio.CancelledError:
        update_run(run_id, status=RunStatus.cancelled, finished_at=datetime.now(timezone.utc))
        await emit_event(run_id, {"type": "error", "message": "Analysis cancelled.", "code": "cancelled"})
        raise
    except Exception:
        logger.exception("Pipeline failed for run %s", run_id)
        update_session(session_id, status=SessionStatus.failed)
        update_run(
            run_id,
            status=RunStatus.failed,
            error_code="pipeline_failed",
            error_message="Analysis failed. Please try again.",
            finished_at=datetime.now(timezone.utc),
        )
        await emit_event(run_id, {"type": "error", "message": "Analysis failed. Please try again.", "code": "pipeline_failed"})
