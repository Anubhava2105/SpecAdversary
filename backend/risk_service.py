"""Risk Register business-logic service.

All risk-related DB mutations flow through this module so the API layer
and the pipeline runner share identical semantics.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, select

from database import engine
from models import Risk, RiskComment, RiskStatus, SpecSession

logger = logging.getLogger(__name__)

# ── Status-transition rules ────────────────────────────────────────────────
# Values are the set of statuses from which you can transition *to* the key.
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "open": {"mitigating", "accepted", "deferred", "dismissed", "resolved"},
    "mitigating": {"open", "accepted", "deferred", "dismissed"},
    "accepted": {"open", "mitigating", "deferred", "dismissed"},
    "deferred": {"open", "mitigating", "accepted", "dismissed"},
    "dismissed": {"open", "mitigating", "accepted", "deferred"},
    "resolved": {"open", "mitigating", "accepted"},
}


def validate_status_transition(old: str, new: str) -> bool:
    """Return True if transitioning from *old* → *new* is allowed."""
    if old == new:
        return True
    allowed_from = _VALID_TRANSITIONS.get(new, set())
    return old in allowed_from


# ── Upsert from pipeline findings ──────────────────────────────────────────

def upsert_risks_from_findings(
    session_id: UUID,
    findings: list[dict],
    run_id: UUID | None = None,
) -> list[Risk]:
    """Create or update Risk rows from pipeline findings.

    AI-owned fields are always overwritten; user-managed fields (status,
    owner_id, validation_plan, due_date, confidence) are preserved on update.
    """
    if not findings:
        return []

    now = datetime.now(timezone.utc)
    upserted: list[Risk] = []

    with Session(engine) as db:
        for f in findings:
            finding_id = f.get("id")
            if not finding_id:
                continue

            existing = db.exec(
                select(Risk).where(
                    Risk.session_id == session_id,
                    Risk.finding_id == finding_id,
                )
            ).first()

            if existing:
                # Update AI-owned fields only
                existing.critic = f.get("critic", existing.critic)
                existing.severity = f.get("severity", existing.severity)
                existing.claim = f.get("claim", existing.claim)
                existing.critique = f.get("critique", existing.critique)
                existing.suggested_fix = f.get("suggested_fix", existing.suggested_fix)
                if run_id:
                    existing.source_run_id = run_id
                existing.updated_at = now
                db.add(existing)
                upserted.append(existing)
            else:
                risk = Risk(
                    session_id=session_id,
                    finding_id=finding_id,
                    critic=f.get("critic", ""),
                    severity=f.get("severity", ""),
                    claim=f.get("claim", ""),
                    critique=f.get("critique", ""),
                    suggested_fix=f.get("suggested_fix"),
                    status=RiskStatus.open.value,
                    source_run_id=run_id,
                    created_at=now,
                    updated_at=now,
                )
                db.add(risk)
                upserted.append(risk)

        db.commit()
        for r in upserted:
            db.refresh(r)

    return upserted


# ── Lazy backfill for legacy sessions ──────────────────────────────────────

def backfill_risks_for_session(session_id: UUID) -> list[Risk]:
    """If a session has JSON findings but zero Risk rows, create them.

    Idempotent: checks for existing risks before inserting.
    """
    with Session(engine) as db:
        session = db.get(SpecSession, session_id)
        if not session or not session.findings:
            return []

        existing_count = db.exec(
            select(Risk).where(Risk.session_id == session_id)
        ).first()
        if existing_count is not None:
            return []  # Already has risks — skip

        return upsert_risks_from_findings(session_id, session.findings)


# ── Summary aggregation ────────────────────────────────────────────────────

def get_risk_summary(session_id: UUID) -> dict:
    """Aggregate counts by status and severity for dashboard display."""
    with Session(engine) as db:
        risks = db.exec(
            select(Risk).where(Risk.session_id == session_id)
        ).all()

    now = datetime.now(timezone.utc)
    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    overdue = 0
    unassigned = 0
    total = len(risks)

    for r in risks:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        if r.severity:
            by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        
        due = r.due_date.replace(tzinfo=timezone.utc) if r.due_date and r.due_date.tzinfo is None else r.due_date
        if due and due < now and r.status not in ("resolved", "dismissed"):
            overdue += 1
        if r.owner_id is None and r.status not in ("resolved", "dismissed"):
            unassigned += 1

    return {
        "total": total,
        "by_status": by_status,
        "by_severity": by_severity,
        "overdue": overdue,
        "unassigned": unassigned,
        "resolved": by_status.get("resolved", 0),
    }
