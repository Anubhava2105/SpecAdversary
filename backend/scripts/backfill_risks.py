"""One-time backfill: create Risk rows for legacy sessions that still have
JSON findings but no normalized RiskRegister rows.

Run once after deploying the Risk Register schema:

    python scripts/backfill_risks.py

Replaces the per-request lazy backfill that previously ran inside
GET /sessions/{sid}/risks and GET /sessions/{sid}/risk-summary.
Idempotent: sessions that already have risks are skipped, so re-running is safe.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from db.database import engine  # noqa: E402
from db.models import Risk, SpecSession  # noqa: E402
from services.risk_service import upsert_risks_from_findings  # noqa: E402

logger = logging.getLogger("backfill_risks")
logging.basicConfig(level=logging.INFO)


def main() -> None:
    with Session(engine) as db:
        candidates = db.exec(select(SpecSession)).all()
        pending = [
            s for s in candidates
            if s.findings and not db.exec(select(Risk).where(Risk.session_id == s.id)).first()
        ]

    logger.info("%d legacy session(s) to backfill", len(pending))
    migrated = 0
    for session in pending:
        risks = upsert_risks_from_findings(session.id, session.findings)
        migrated += len(risks)
        logger.info("session %s: %d risk(s) created", session.id, len(risks))

    logger.info("done: %d risk(s) created across %d session(s)", migrated, len(pending))


if __name__ == "__main__":
    main()
