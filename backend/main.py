"""Composition root: builds the FastAPI app from the route modules and owns
the middleware, lifespan, and health check. All endpoint logic lives in the
route modules; shared infrastructure state lives in deps."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from core.logging_config import setup_logging  # noqa: E402

setup_logging()

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlmodel import Session

from core import deps
from core.broker import client as redis_client
from core.deps import (
    IS_PRODUCTION,
    limiter,
    validate_production_config,
)
from core.deps import (
    client_key as client_key,  # noqa: F401  (test-facing re-export)
)
from core.deps import (
    reserve_daily_session as reserve_daily_session,  # noqa: F401  (test-facing re-export)
)
from db.database import engine
from routes import auth_routes, risk_routes, session_routes, stream_routes
from routes.auth_routes import _oauth_upsert as _oauth_upsert  # noqa: F401  (test-facing re-export)
from routes.session_routes import (
    restart_pipeline_args as restart_pipeline_args,  # noqa: F401  (test-facing re-export)
)
from routes.session_routes import (
    session_snapshot_events as session_snapshot_events,  # noqa: F401  (test-facing re-export)
)

logger = logging.getLogger(__name__)

class SecurityHeadersMiddleware:
    """Raw ASGI middleware — skips WebSocket connections (unlike BaseHTTPMiddleware)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    # The API serves no HTML; deny everything so injected
                    # content has no execution path even on error pages.
                    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
                ]
                if IS_PRODUCTION:
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)

@asynccontextmanager
async def lifespan(app):
    validate_production_config()
    reaper_task = asyncio.create_task(deps.reaper_loop())
    yield
    reaper_task.cancel()

app=FastAPI(title="Spec Adversary",lifespan=lifespan, docs_url=None if os.environ.get("ENV") == "production" else "/docs")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(deps.ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.add_middleware(SecurityHeadersMiddleware)


@app.get("/healthz")
async def healthz():
    """Liveness + dependency readiness: DB and Redis must answer to serve traffic."""
    checks: dict[str, str] = {}
    try:
        with Session(engine) as db:
            db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        logger.warning("Health check: database unreachable", exc_info=True)
        checks["db"] = f"error: {type(exc).__name__}"

    try:
        await redis_client().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("Health check: redis unreachable", exc_info=True)
        checks["redis"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ok" if healthy else "degraded", **checks},
    )


app.include_router(risk_routes.router)
app.include_router(auth_routes.router)
app.include_router(session_routes.router)
app.include_router(stream_routes.router)
