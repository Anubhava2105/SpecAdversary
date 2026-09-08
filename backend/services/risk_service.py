"""Risk Register business-logic service.

All risk-related DB mutations flow through this module so the API layer
and the pipeline runner share identical semantics.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, select

from db.database import engine
from db.models import Risk, RiskStatus, SpecSession
from services.lifecycle import as_utc

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


def _coerce_status(value: str | RiskStatus) -> RiskStatus | None:
    try:
        return value if isinstance(value, RiskStatus) else RiskStatus(value)
    except ValueError:
        return None


def validate_status_transition(old: str | RiskStatus, new: str | RiskStatus) -> bool:
    """Return True if transitioning from *old* → *new* is allowed.

    Unknown statuses are never legal — including the reflexive case, so
    ("bogus", "bogus") is False.
    """
    old_status, new_status = _coerce_status(old), _coerce_status(new)
    if old_status is None or new_status is None:
        return False
    if old_status == new_status:
        return True
    return old_status.value in _VALID_TRANSITIONS.get(new_status.value, set())


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
    """Create Risk rows for session findings that lack them.

    Idempotent: findings that already have a Risk row are skipped, so partial
    backfills complete on re-run instead of being skipped entirely.
    """
    with Session(engine) as db:
        session = db.get(SpecSession, session_id)
        if not session or not session.findings:
            return []

        existing_ids = set(
            db.exec(select(Risk.finding_id).where(Risk.session_id == session_id)).all()
        )
        missing = [f for f in session.findings if f.get("id") not in existing_ids]
        if not missing:
            return []  # Already has risks — skip

        return upsert_risks_from_findings(session_id, missing)


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

        due = as_utc(r.due_date)
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
