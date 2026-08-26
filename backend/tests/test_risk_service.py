"""Tests for risk_service business logic."""
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from db.database import engine
from db.models import Risk, RiskStatus, SpecSession
from services.risk_service import (
    backfill_risks_for_session,
    get_risk_summary,
    upsert_risks_from_findings,
    validate_status_transition,
)


def _make_session(db: Session, findings: list[dict] | None = None) -> SpecSession:
    s = SpecSession(raw_spec="test spec", findings=findings or [])
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _sample_findings(n: int = 3) -> list[dict]:
    return [
        {
            "id": f"f{i}",
            "critic": "assumption",
            "severity": "significant",
            "claim": f"Claim {i}",
            "critique": f"Critique {i}",
            "suggested_fix": f"Fix {i}",
        }
        for i in range(n)
    ]


# ── upsert_risks_from_findings ────────────────────────────────────────────
def test_upsert_creates_risks_from_findings():
    with Session(engine) as db:
        session = _make_session(db)
        findings = _sample_findings(3)
        risks = upsert_risks_from_findings(session.id, findings)
        assert len(risks) == 3
        assert all(r.session_id == session.id for r in risks)
        assert risks[0].claim == "Claim 0"
        assert risks[0].status == RiskStatus.open


def test_upsert_preserves_user_fields():
    with Session(engine) as db:
        session = _make_session(db)
        findings = _sample_findings(1)
        upsert_risks_from_findings(session.id, findings)

        # Manually change user fields
        risk = db.exec(
            __import__("sqlmodel").select(Risk).where(Risk.session_id == session.id)
        ).first()
        risk.status = RiskStatus.mitigating.value
        risk.validation_plan = "My plan"
        risk.confidence = 75
        db.add(risk)
        db.commit()

        # Re-upsert with updated AI fields
        findings[0]["claim"] = "Updated claim"
        findings[0]["severity"] = "structural"
        upsert_risks_from_findings(session.id, findings)

        db.refresh(risk)
        assert risk.claim == "Updated claim"
        assert risk.severity == "structural"
        # User fields preserved
        assert risk.status == RiskStatus.mitigating.value
        assert risk.validation_plan == "My plan"
        assert risk.confidence == 75


def test_upsert_idempotent():
    with Session(engine) as db:
        session = _make_session(db)
        findings = _sample_findings(2)
        upsert_risks_from_findings(session.id, findings)
        upsert_risks_from_findings(session.id, findings)

        risks = db.exec(
            __import__("sqlmodel").select(Risk).where(Risk.session_id == session.id)
        ).all()
        assert len(risks) == 2


# ── backfill_risks_for_session ────────────────────────────────────────────
def test_backfill_from_legacy_session():
    with Session(engine) as db:
        findings = _sample_findings(2)
        session = _make_session(db, findings=findings)

        risks = backfill_risks_for_session(session.id)
        assert len(risks) == 2


def test_backfill_idempotent():
    with Session(engine) as db:
        findings = _sample_findings(2)
        session = _make_session(db, findings=findings)

        backfill_risks_for_session(session.id)
        second = backfill_risks_for_session(session.id)
        assert len(second) == 0


# ── validate_status_transition ────────────────────────────────────────────
def test_status_transitions():
    assert validate_status_transition(RiskStatus.open, RiskStatus.mitigating) is True
    assert validate_status_transition(RiskStatus.open, RiskStatus.resolved) is True
    assert validate_status_transition(RiskStatus.dismissed, RiskStatus.mitigating) is True
    assert validate_status_transition(RiskStatus.dismissed, RiskStatus.open) is True
    assert validate_status_transition(RiskStatus.deferred, RiskStatus.resolved) is False
    assert validate_status_transition(RiskStatus.open, RiskStatus.open) is True


# ── get_risk_summary ──────────────────────────────────────────────────────
def test_resolved_at_auto_set():
    with Session(engine) as db:
        session = _make_session(db)
        findings = _sample_findings(1)
        risks = upsert_risks_from_findings(session.id, findings)
        risk = risks[0]

        # Resolve
        risk.status = RiskStatus.resolved.value
        risk.resolved_at = datetime.now(timezone.utc)
        db.add(risk)
        db.commit()
        db.refresh(risk)
        assert risk.resolved_at is not None

        # Reopen
        risk.status = RiskStatus.open.value
        risk.resolved_at = None
        db.add(risk)
        db.commit()
        db.refresh(risk)
        assert risk.resolved_at is None


def test_risk_summary_counts():
    with Session(engine) as db:
        session = _make_session(db)
        findings = _sample_findings(4)
        risks = upsert_risks_from_findings(session.id, findings)

        # Set different statuses
        risks[0].status = RiskStatus.open.value
        risks[1].status = RiskStatus.mitigating.value
        risks[2].status = RiskStatus.resolved.value
        risks[2].resolved_at = datetime.now(timezone.utc)
        risks[3].status = RiskStatus.open.value
        risks[3].due_date = datetime.now(timezone.utc) - timedelta(days=1)  # overdue
        for r in risks:
            db.add(r)
        db.commit()

        summary = get_risk_summary(session.id)
        assert summary["total"] == 4
        assert summary["by_status"].get("open", 0) == 2
        assert summary["by_status"].get("mitigating", 0) == 1
        assert summary["by_status"].get("resolved", 0) == 1
        assert summary["overdue"] == 1
