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
from db.models import SpecSession  # noqa: E402
from services.risk_service import backfill_risks_for_session  # noqa: E402

logger = logging.getLogger("backfill_risks")
logging.basicConfig(level=logging.INFO)


def main() -> None:
    with Session(engine) as db:
        candidate_ids = [
            s.id for s in db.exec(select(SpecSession)).all() if s.findings
        ]

    logger.info("%d session(s) with findings to inspect", len(candidate_ids))
    sessions_touched = 0
    migrated = 0
    for session_id in candidate_ids:
        try:
            risks = backfill_risks_for_session(session_id)
        except Exception:
            # One bad session (e.g. a concurrent pipeline upsert racing the
            # unique constraint) must not abort the whole backfill; the
            # service is idempotent so re-running completes the remainder.
            logger.warning("session %s: skipped after error", session_id, exc_info=True)
            continue
        if risks:
            sessions_touched += 1
            migrated += len(risks)
            logger.info("session %s: %d risk(s) created", session_id, len(risks))

    logger.info("done: %d risk(s) created across %d session(s)", migrated, sessions_touched)


if __name__ == "__main__":
    main()
