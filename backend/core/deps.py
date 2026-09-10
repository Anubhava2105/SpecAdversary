"""Shared infrastructure state for the backend app.

Owns the configuration constants, the rate limiter, audit logging, the
prompt-injection and daily-budget guards, and run dispatch — the globals
every router shares. Session access control lives in ``core.ownership``
(the Ownership Rule's own module); the names are re-exported here so
existing import sites keep working. Tests patch ``deps.dispatch_run`` and
flip ``deps.limiter.enabled`` here instead of reaching into ``main``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from uuid import UUID

from dotenv import load_dotenv

load_dotenv()

from arq import create_pool  # noqa: E402
from arq.connections import RedisSettings  # noqa: E402
from fastapi import HTTPException, Request, status  # noqa: E402
from slowapi import Limiter  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402
from sqlalchemy import func, text  # noqa: E402
from sqlmodel import Session, col, select  # noqa: E402

from core.broker import ARQ_QUEUE_NAME, REDIS_URL  # noqa: E402
from core.ownership import (  # noqa: E402  (Ownership Rule lives here; re-exported for existing import sites)
    can_access_session as can_access_session,
)
from core.ownership import (
    require_risk_access as require_risk_access,
)
from core.ownership import (
    require_session_access as require_session_access,
)
from db.database import engine  # noqa: E402
from db.models import SpecSession, User  # noqa: E402
from services.pipeline_runner import execute_run  # noqa: E402

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")

ENV = os.getenv("ENV", "development")
IS_PRODUCTION = ENV == "production"

def validate_production_config() -> None:
    """Refuse to boot in production with unsafe defaults."""
    if not IS_PRODUCTION:
        return
    problems = []
    secret = os.getenv("JWT_SECRET", "")
    if len(secret) < 32 or secret.startswith("dev-insecure"):
        problems.append("JWT_SECRET must be a unique random value of at least 32 characters")
    frontend = os.getenv("FRONTEND_URL", "")
    if not frontend or "localhost" in frontend or "127.0.0.1" in frontend:
        problems.append("FRONTEND_URL must be set to the production public origin")
    if os.getenv("RATELIMIT_STORAGE_URI", "memory://") == "memory://":
        problems.append("RATELIMIT_STORAGE_URI must point at shared Redis so replicas share buckets")
    if os.getenv("DEV_NO_LIMITS", "false").lower() == "true":
        problems.append("DEV_NO_LIMITS must never be enabled in production")
    if problems:
        raise RuntimeError("Refusing to start in production with unsafe configuration: " + "; ".join(problems))

if IS_PRODUCTION:
    ALLOWED_ORIGINS = {
        os.getenv("CORS_ORIGIN", "https://specadversary.com"),
        os.getenv("FRONTEND_URL", "https://specadversary.com"),
    }
else:
    ALLOWED_ORIGINS = {
        os.getenv("CORS_ORIGIN", "https://specadversary.com"),
        "http://localhost:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5173",
    }
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5174")
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"


def limits_disabled() -> bool:
    """True only for local development with DEV_NO_LIMITS=true.

    Disables rate limiting and daily session budgets so the platform can be
    exercised freely in guest and signed-in sessions while developing.
    Never true in production (startup validation refuses that combination).
    """
    return not IS_PRODUCTION and os.getenv("DEV_NO_LIMITS", "false").lower() == "true"


DAILY_SESSION_LIMIT = 100
PER_USER_DAILY_LIMIT = int(os.getenv("PER_USER_DAILY_SESSION_LIMIT", "25"))
INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\b(?:output|reveal|show|print)\s+(?:your\s+)?system\s+prompt\b", re.IGNORECASE),
)

def client_key(request: Request) -> str:
    """Rate-limit identity. Behind a trusted proxy the browser IP arrives in
    X-Forwarded-For; without this every visitor shares the proxy's address
    and drains one collective bucket."""
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)

# Shared across processes/replicas via Redis when configured; memory:// keeps
# single-process local development working without infrastructure.
limiter = Limiter(
    key_func=client_key,
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
)
inline_tasks: set[asyncio.Task] = set()

# Session access control moved to core.ownership (Candidate 4); the
# implementations are re-exported above. What remains here is rate
# limiting, budgets, audit logging, and dispatch.

def reject_prompt_injection(raw_spec: str, client_ip: str) -> None:
    """Reject obvious instruction-override attempts before they reach an LLM."""
    if any(pattern.search(raw_spec) for pattern in INJECTION_PATTERNS):
        audit_logger.warning("prompt_injection_blocked - IP: %s - Preview: %s", client_ip, raw_spec[:200])
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Spec contains a disallowed prompt-injection phrase")

def _utc_day_start() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def per_user_sessions_today(db: Session, user_id: UUID) -> int:
    """Sessions this user created since UTC midnight — the single home for the
    per-user count so the pre-check and the insert-time enforcement agree."""
    return db.exec(
        select(func.count(col(SpecSession.id))).where(
            SpecSession.user_id == user_id,
            SpecSession.created_at >= _utc_day_start(),
        )
    ).one()


def reserve_daily_session(user: User | None = None) -> None:
    """Reserve one of today's session budget slots.

    Authenticated users draw from a per-user allowance first (best-effort
    pre-check; the authoritative enforcement happens inside the session-insert
    transaction in the sessions route); the global SQLite-backed budget
    remains as an atomic runaway backstop. Skipped entirely when local
    development limits are disabled (DEV_NO_LIMITS=true).
    """
    if limits_disabled():
        return
    if user is not None:
        with Session(engine) as db:
            created_today = per_user_sessions_today(db, user.id)
        if created_today >= PER_USER_DAILY_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily limit of {PER_USER_DAILY_LIMIT} analyses reached; try again tomorrow",
            )

    day = datetime.now(timezone.utc).date().isoformat()
    # A single UPSERT closes the read/increment/write race between concurrent
    # requests; `RETURNING` is supported by the SQLite versions SQLAlchemy uses.
    statement = text("""
        INSERT INTO daily_usage (day, sessions_created) VALUES (:day, 1)
        ON CONFLICT(day) DO UPDATE SET sessions_created = daily_usage.sessions_created + 1
        WHERE daily_usage.sessions_created < :limit
        RETURNING sessions_created
    """)
    with engine.begin() as connection:
        reserved = connection.execute(statement, {"day": day, "limit": DAILY_SESSION_LIMIT}).scalar_one_or_none()
    if reserved is None:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Daily session limit reached; try again tomorrow")

def inline_enabled() -> bool:
    """True only for explicit local development without a worker service."""
    return os.getenv("INLINE_WORKER", "false").lower() == "true"


async def dispatch_run(run_id: UUID) -> None:
    """Enqueue an analysis job for ARQ workers; inline execution is only
    for explicit local development (no worker service running)."""
    if inline_enabled():
        task = asyncio.create_task(execute_run(run_id))
        setattr(task, "run_id", run_id)
        inline_tasks.add(task)
        task.add_done_callback(inline_tasks.discard)
        return
    # A short-lived pool per dispatch: session creation is human-frequency,
    # so one connection setup per call costs nothing and needs no lifespan
    # wiring. The function name must match worker.py's registered job, and
    # the job id must match the run id so cancel can abort a queued job.
    pool = await create_pool(
        RedisSettings.from_dsn(REDIS_URL), default_queue_name=ARQ_QUEUE_NAME
    )
    try:
        await pool.enqueue_job("run_analysis_job", str(run_id), _job_id=str(run_id))
    finally:
        await pool.close()

async def reaper_loop() -> None:
    """API-side safety net for orphaned runs (worker runs its own sweep)."""
    from services.pipeline_runner import reap_stuck_runs
    while True:
        await asyncio.sleep(60)
        try:
            await reap_stuck_runs()
        except Exception:
            logger.exception("Stuck-run sweep failed")
