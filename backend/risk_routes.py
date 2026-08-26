"""Risk Register REST surface: list, summarize, inspect, patch, comment on,
and re-evaluate Risks. The human-workable side of a Session's Findings."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, col, select

import deps
import lifecycle
from auth import get_optional_user
from database import engine
from models import (
    AnalysisRun,
    Risk,
    RiskComment,
    RiskStatus,
    SpecSession,
    User,
)
from risk_service import (
    get_risk_summary,
    validate_status_transition,
)

router = APIRouter()

# ── Risk Register payloads ─────────────────────────────────────────────────
class RiskPatchPayload(BaseModel):
    status: str | None = None
    validation_plan: str | None = Field(default=None, max_length=5000)
    owner_id: str | None = None  # "self" or null to unassign
    due_date: str | None = None  # ISO 8601 or null to clear
    confidence: int | None = Field(default=None, ge=0, le=100)


class RiskCommentPayload(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class RiskCommentResponse(BaseModel):
    id: str
    risk_id: str
    author_id: str | None
    author_email: str | None = None
    body: str
    created_at: str


class RiskResponse(BaseModel):
    id: str
    session_id: str
    finding_id: str | None
    critic: str
    severity: str
    claim: str
    critique: str
    suggested_fix: str | None
    confidence: int | None
    evidence: list[dict] | None
    validation_plan: str | None
    status: str
    owner_id: str | None
    owner_email: str | None = None
    due_date: str | None
    source_run_id: str | None
    created_at: str
    updated_at: str
    resolved_at: str | None
    comments: list[RiskCommentResponse] | None = None


class RiskSummaryResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    overdue: int
    unassigned: int


class RiskListResponse(BaseModel):
    items: list[RiskResponse]
    total: int
    summary: RiskSummaryResponse


def _risk_to_response(risk: Risk, *, comments: list[RiskCommentResponse] | None = None, owner_email: str | None = None) -> RiskResponse:
    return RiskResponse(
        id=str(risk.id),
        session_id=str(risk.session_id),
        finding_id=risk.finding_id,
        critic=risk.critic,
        severity=risk.severity,
        claim=risk.claim,
        critique=risk.critique,
        suggested_fix=risk.suggested_fix,
        confidence=risk.confidence,
        evidence=risk.evidence or [],
        validation_plan=risk.validation_plan,
        status=risk.status if isinstance(risk.status, str) else risk.status.value,
        owner_id=str(risk.owner_id) if risk.owner_id else None,
        owner_email=owner_email,
        due_date=risk.due_date.isoformat() if risk.due_date else None,
        source_run_id=str(risk.source_run_id) if risk.source_run_id else None,
        created_at=risk.created_at.isoformat(),
        updated_at=risk.updated_at.isoformat(),
        resolved_at=risk.resolved_at.isoformat() if risk.resolved_at else None,
        comments=comments,
    )


# ── Risk Register endpoints ───────────────────────────────────────────────
@router.get("/sessions/{sid}/risks")
@deps.limiter.limit("30/minute")
async def list_risks(
    request: Request,
    sid: UUID,
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = None,
    critic: str | None = None,
    search: str | None = None,
    sort_by: str = "severity",
    sort_dir: str = "desc",
    offset: int = 0,
    limit: int = 50,
    user: User | None = Depends(get_optional_user),
):
    with Session(engine) as db:
        session_row = db.get(SpecSession, sid)
        if not session_row:
            raise HTTPException(404, "Session not found")
        if not deps.can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        # Legacy sessions are migrated once by scripts/backfill_risks.py; this
        # endpoint no longer pays for a backfill probe on every request.

        query = select(Risk).where(Risk.session_id == sid)
        if status_filter:
            query = query.where(Risk.status == status_filter)
        if severity:
            query = query.where(Risk.severity == severity)
        if critic:
            query = query.where(Risk.critic == critic)
        if search:
            query = query.where(col(Risk.claim).contains(search))

        # Sorting
        SORT_COLUMNS: dict[str, Any] = {
            "severity": col(Risk.severity),
            "created_at": col(Risk.created_at),
            "updated_at": col(Risk.updated_at),
            "due_date": col(Risk.due_date),
            "status": col(Risk.status),
        }
        sort_col = SORT_COLUMNS.get(sort_by, col(Risk.severity))
        query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

        total = db.exec(select(func.count()).select_from(query.subquery())).one()
        paginated = db.exec(query.offset(offset).limit(limit)).all()

        items = [_risk_to_response(r) for r in paginated]

    summary = get_risk_summary(sid)
    return RiskListResponse(items=items, total=total, summary=RiskSummaryResponse(**summary))


@router.get("/sessions/{sid}/risk-summary")
@deps.limiter.limit("30/minute")
async def risk_summary(request: Request, sid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        session_row = db.get(SpecSession, sid)
        if not session_row:
            raise HTTPException(404, "Session not found")
        if not deps.can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        summary = get_risk_summary(sid)

    return RiskSummaryResponse(**summary)


@router.get("/risks/{rid}")
@deps.limiter.limit("30/minute")
async def get_risk_detail(request: Request, rid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        risk = db.get(Risk, rid)
        if not risk:
            raise HTTPException(404, "Risk not found")
        session_row = db.get(SpecSession, risk.session_id)
        if not session_row or not deps.can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        comments_rows = db.exec(
            select(RiskComment).where(RiskComment.risk_id == rid).order_by(col(RiskComment.created_at))
        ).all()
        # One batched lookup instead of a per-comment author fetch (N+1).
        author_ids = {c.author_id for c in comments_rows if c.author_id}
        emails: dict[UUID, str] = {}
        if author_ids:
            authors = db.exec(select(User).where(col(User.id).in_(author_ids))).all()
            emails = {a.id: a.email for a in authors}
        comments = []
        for c in comments_rows:
            comments.append(RiskCommentResponse(
                id=str(c.id),
                risk_id=str(c.risk_id),
                author_id=str(c.author_id) if c.author_id else None,
                author_email=emails.get(c.author_id) if c.author_id else None,
                body=c.body,
                created_at=c.created_at.isoformat(),
            ))

        owner_email = None
        if risk.owner_id:
            owner = db.get(User, risk.owner_id)
            owner_email = owner.email if owner else None

        return _risk_to_response(risk, comments=comments, owner_email=owner_email)


@router.patch("/risks/{rid}")
@deps.limiter.limit("30/minute")
async def patch_risk(request: Request, rid: UUID, payload: RiskPatchPayload, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        risk = db.get(Risk, rid)
        if not risk:
            raise HTTPException(404, "Risk not found")
        session_row = db.get(SpecSession, risk.session_id)
        if not session_row or not deps.can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        # Status transition
        if payload.status is not None:
            try:
                new_status = RiskStatus(payload.status)
            except ValueError:
                raise HTTPException(400, f"Invalid status: {payload.status}")
            old_status = RiskStatus(risk.status) if isinstance(risk.status, str) else risk.status
            if not validate_status_transition(old_status, new_status):
                raise HTTPException(
                    400,
                    f"Cannot transition from '{old_status.value}' to '{new_status.value}'"
                )
            risk.status = new_status.value
            # Auto-manage resolved_at
            if new_status == RiskStatus.resolved:
                risk.resolved_at = datetime.now(timezone.utc)
            elif old_status == RiskStatus.resolved:
                risk.resolved_at = None

        # Validation plan
        if payload.validation_plan is not None:
            risk.validation_plan = payload.validation_plan

        # Owner assignment — auth-only per user decision
        if payload.owner_id is not None:
            if payload.owner_id == "self":
                if user is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required to assign ownership")
                risk.owner_id = user.id
            elif payload.owner_id == "":
                risk.owner_id = None
            else:
                raise HTTPException(400, "owner_id must be 'self' or empty string to unassign")

        # Due date
        if payload.due_date is not None:
            if payload.due_date == "":
                risk.due_date = None
            else:
                try:
                    risk.due_date = datetime.fromisoformat(payload.due_date)
                except ValueError:
                    raise HTTPException(400, "Invalid due_date format (use ISO 8601)")

        # Confidence
        if payload.confidence is not None:
            risk.confidence = payload.confidence

        risk.updated_at = datetime.now(timezone.utc)
        db.add(risk)
        db.commit()
        db.refresh(risk)

        owner_email = None
        if risk.owner_id:
            owner = db.get(User, risk.owner_id)
            owner_email = owner.email if owner else None

        return _risk_to_response(risk, owner_email=owner_email)


@router.post("/risks/{rid}/comments")
@deps.limiter.limit("30/minute")
async def add_risk_comment(request: Request, rid: UUID, payload: RiskCommentPayload, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        risk = db.get(Risk, rid)
        if not risk:
            raise HTTPException(404, "Risk not found")
        session_row = db.get(SpecSession, risk.session_id)
        if not session_row or not deps.can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        comment = RiskComment(
            risk_id=rid,
            author_id=user.id if user else None,
            body=payload.body,
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)

        author_email = user.email if user else None
        return RiskCommentResponse(
            id=str(comment.id),
            risk_id=str(comment.risk_id),
            author_id=str(comment.author_id) if comment.author_id else None,
            author_email=author_email,
            body=comment.body,
            created_at=comment.created_at.isoformat(),
        )


@router.post("/risks/{rid}/re-evaluate")
@deps.limiter.limit("5/minute")
async def re_evaluate_risk(request: Request, rid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        risk = db.get(Risk, rid)
        if not risk:
            raise HTTPException(404, "Risk not found")
        session_row = db.get(SpecSession, risk.session_id)
        if not session_row or not deps.can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
        if not lifecycle.accepts_client_activity(session_row.status):
            raise HTTPException(status.HTTP_409_CONFLICT, "Analysis is still in progress for this session")

        if not risk.finding_id:
            raise HTTPException(400, "Cannot re-evaluate a risk without a finding_id")

        run = AnalysisRun(session_id=risk.session_id, re_evaluate_finding_id=risk.finding_id)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

    await deps.dispatch_run(run_id)
    return {"status": "queued", "run_id": str(run_id)}
