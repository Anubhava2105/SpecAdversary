"""Ownership Rule: the single home for session access control.

Guest Sessions (``user_id`` None) are open; owned Sessions are closed to
everyone but their owner. Every access path enforces this identically —
REST routes call ``require_session_access`` / ``require_risk_access``
instead of reimplementing the check.

Billing entitlement checks will sit beside these helpers when that work
starts; that is the moment this shared home pays off beyond locality.

Domain terms follow ``CONTEXT.md``.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import Session

from db.models import Risk, SpecSession, User


def can_access_session(session_row: SpecSession, user: User | None) -> bool:
    """Guest sessions (user_id=None) are open. Owned sessions require the matching user."""
    if session_row.user_id is None:
        return True
    return user is not None and session_row.user_id == user.id


def require_session_access(db: Session, sid: UUID, user: User | None) -> SpecSession:
    """Load a Session and enforce the Ownership Rule at one seam.

    404 when the Session does not exist, 403 when it is owned by someone else.
    Every REST access path goes through here so the rule cannot drift.
    """
    row = db.get(SpecSession, sid)
    if row is None:
        raise HTTPException(404, "Session not found")
    if not can_access_session(row, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
    return row


def require_risk_access(db: Session, rid: UUID, user: User | None) -> tuple[Risk, SpecSession]:
    """Load a Risk (404 when absent) and enforce the Ownership Rule via its
    Session (403 when closed). Returns both rows; the Session's status is
    often needed for in-flight guards."""
    risk = db.get(Risk, rid)
    if risk is None:
        raise HTTPException(404, "Risk not found")
    session_row = db.get(SpecSession, risk.session_id)
    if not session_row or not can_access_session(session_row, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
    return risk, session_row
