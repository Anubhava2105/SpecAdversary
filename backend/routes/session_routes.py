"""Session CRUD routes: start an Analysis, reply to a Finding, list and
inspect Sessions, and mint WebSocket stream tickets."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from core import deps
from core.auth import create_websocket_ticket, get_current_user, get_optional_user
from core.ownership import require_session_access
from db.database import engine
from db.models import AnalysisRun, Critic, SessionStatus, SpecSession, User
from services import lifecycle
from services import panel as panel_registry

router = APIRouter()

# ── Existing logic (preserved) ─────────────────────────────────────────────
class CreateSession(BaseModel):
    raw_spec: str = Field(min_length=1, max_length=10_000)
    # Defaults derive from the panel registry — adding a critic there
    # changes the default fan-out without touching this schema.
    selected_critics: list[Critic] = Field(
        min_length=1,
        default_factory=lambda: [Critic(c) for c in panel_registry.DEFAULT_CRITICS],
    )

class ReplyPayload(BaseModel):
    reply: str = Field(min_length=1, max_length=2_000)


def session_snapshot_events(row: SpecSession):
    """Persistent events replayed to a late WebSocket subscriber."""
    yield {"type": "status", "status": row.status.value}
    yield {"type": "gatekeeper", "missing_context": row.missing_context or []}
    for section, content in row.parsed_sections.items():
        yield {"type": "section_parsed", "section": section, "content": content}
    for finding in row.findings:
        yield {"type": "finding", "finding": finding}
    if row.status == SessionStatus.done:
        yield {"type": "done", "revised_spec": row.revised_spec or ""}


def restart_pipeline_args(row: SpecSession) -> tuple[UUID, str, list[str]]:
    """Compatibility helper retained for callers migrating to durable runs."""
    return row.id, row.raw_spec, row.selected_critics


@router.post("/sessions")
@deps.limiter.limit("5/hour")
async def create_session(request: Request, payload: CreateSession, user: User | None = Depends(get_optional_user)):
    deps.reject_prompt_injection(payload.raw_spec, request.client.host if request.client else "unknown")
    deps.reserve_daily_session(user)
    selected = [c.value for c in payload.selected_critics]
    row = SpecSession(raw_spec=payload.raw_spec, selected_critics=selected, user_id=user.id if user else None)
    with Session(engine) as db:
        db.add(row)
        db.flush()
        # Authoritative per-user enforcement inside the insert transaction:
        # the pre-check in reserve_daily_session is a fast fail, this closes
        # the concurrent-insert race (both checks share one helper).
        # Skipped when local development limits are disabled.
        if not deps.limits_disabled() and user is not None and deps.per_user_sessions_today(db, user.id) > deps.PER_USER_DAILY_LIMIT:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily limit of {deps.PER_USER_DAILY_LIMIT} analyses reached; try again tomorrow",
            )
        db.commit()
        db.refresh(row)
        run = AnalysisRun(session_id=row.id)
        db.add(run)
        db.commit()
        db.refresh(run)

        row_id = row.id
        run_id = run.id

    deps.audit_logger.info("session_created - IP: %s - ID: %s", request.client.host if request.client else "unknown", row_id)

    await deps.dispatch_run(run_id)
    return {"id": row_id, "run_id": run_id}

@router.post("/sessions/{sid}/findings/{fid}/reply")
@deps.limiter.limit("5/minute")
async def reply_to_finding(request: Request, sid: UUID, fid: str, payload: ReplyPayload, user: User | None = Depends(get_optional_user)):
    from sqlalchemy.orm.attributes import flag_modified
    with Session(engine) as db:
        row = require_session_access(db, sid, user)
        if not lifecycle.accepts_client_activity(row.status):
            raise HTTPException(status.HTTP_409_CONFLICT, "Analysis is still in progress for this session")

        finding_dict = next((f for f in row.findings if f.get("id") == fid), None)
        if not finding_dict:
            raise HTTPException(404, "Finding not found")

        finding_dict.setdefault("thread", []).append({"role": "user", "content": payload.reply})
        # Mark the JSON column as dirty so SQLAlchemy detects the in-place mutation
        flag_modified(row, "findings")
        db.add(row)
        db.commit()
        # Capture values while row is still attached to the session
        run = AnalysisRun(session_id=row.id, re_evaluate_finding_id=fid)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

    await deps.dispatch_run(run_id)
    return {"status": "queued", "run_id": str(run_id)}

@router.get("/sessions")
@deps.limiter.limit("30/minute")
async def list_sessions(
    request: Request,
    user: User | None = Depends(get_optional_user),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    with Session(engine) as db:
        if user:
            rows = db.exec(
                select(SpecSession)
                .where(SpecSession.user_id == user.id)
                .order_by(col(SpecSession.created_at).desc())
                .offset(offset)
                .limit(limit)
            ).all()
        else:
            # Guests see no history (their sessions are ephemeral)
            rows = []
    return [
        {
            "id": str(row.id),
            "created_at": row.created_at.isoformat(),
            "status": row.status.value,
            "title": row.raw_spec[:80].split("\n")[0] + ("…" if len(row.raw_spec) > 80 else ""),
        }
        for row in rows
    ]

@router.get("/sessions/{sid}")
@deps.limiter.limit("30/minute")
async def get_session(request: Request, sid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        row = require_session_access(db, sid, user)
        data = row.model_dump(mode="json")
        # Latest recorded run spend, so reloaded reports keep their cost
        # readout without replaying the stream. None when no run finished.
        # Filtered in Python: NULL comparisons on SQLModel column attributes
        # fail mypy (declared-type access) and == None fails ruff (E711).
        usages = db.exec(
            select(AnalysisRun.token_usage)
            .where(AnalysisRun.session_id == sid)
            .order_by(col(AnalysisRun.created_at).desc())
        ).all()
        data["token_usage"] = next((u for u in usages if u is not None), None)
    return data


@router.post("/sessions/{sid}/stream-ticket")
@deps.limiter.limit("30/minute")
async def create_stream_ticket(request: Request, sid: UUID, user: User = Depends(get_current_user)):
    with Session(engine) as db:
        require_session_access(db, sid, user)
    return {"ticket": create_websocket_ticket(user.id)}
