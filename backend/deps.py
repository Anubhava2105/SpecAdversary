"""Shared infrastructure state for the backend app.

Owns the configuration constants, the rate limiter, audit logging, the
prompt-injection and daily-budget guards, and run dispatch — the globals
every router shares. Tests patch ``deps.dispatch_run`` and flip
``deps.limiter.enabled`` here instead of reaching into ``main``.
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

from fastapi import HTTPException, Request, status  # noqa: E402
from slowapi import Limiter  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402
from sqlalchemy import func, text  # noqa: E402
from sqlmodel import Session, col, select  # noqa: E402

from broker import enqueue_run  # noqa: E402
from database import engine  # noqa: E402
from models import SpecSession, User  # noqa: E402
from pipeline_runner import execute_run  # noqa: E402

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

def reject_prompt_injection(raw_spec: str, client_ip: str) -> None:
    """Reject obvious instruction-override attempts before they reach an LLM."""
    if any(pattern.search(raw_spec) for pattern in INJECTION_PATTERNS):
        audit_logger.warning("prompt_injection_blocked - IP: %s - Preview: %s", client_ip, raw_spec[:200])
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Spec contains a disallowed prompt-injection phrase")

def reserve_daily_session(user: User | None = None) -> None:
    """Reserve one of today's session budget slots.

    Authenticated users draw from a per-user allowance first; the global
    SQLite-backed budget remains as a runaway backstop.
    """
    if user is not None:
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(engine) as db:
            created_today = db.exec(
                select(func.count(col(SpecSession.id))).where(
                    SpecSession.user_id == user.id,
                    SpecSession.created_at >= day_start,
                )
            ).one()
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

async def dispatch_run(run_id: UUID) -> None:
    """Enqueue for a worker; inline execution is only for explicit local development."""
    if os.getenv("INLINE_WORKER", "false").lower() == "true":
        task = asyncio.create_task(execute_run(run_id))
        inline_tasks.add(task)
        task.add_done_callback(inline_tasks.discard)
        return
    await enqueue_run(run_id)

async def reaper_loop() -> None:
    """API-side safety net for orphaned runs (worker runs its own sweep)."""
    from pipeline_runner import reap_stuck_runs
    while True:
        await asyncio.sleep(60)
        try:
            await reap_stuck_runs()
        except Exception:
            logger.exception("Stuck-run sweep failed")
