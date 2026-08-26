from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlencode
from uuid import UUID

from dotenv import load_dotenv

load_dotenv()

from logging_config import setup_logging  # noqa: E402

setup_logging()

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlmodel import Session, col, select

import deps
import lifecycle
import risk_routes
from auth import (
    GITHUB_CLIENT_ID,
    GOOGLE_CLIENT_ID,
    create_access_token,
    create_refresh_token,
    create_websocket_ticket,
    decode_token,
    exchange_github_code,
    exchange_google_code,
    get_current_user,
    get_optional_user,
    hash_password,
    revoke_user_refresh_tokens,
    rotate_refresh_token,
    verify_password,
)
from broker import client as redis_client
from broker import subscribe_run
from database import engine
from deps import (
    ALLOWED_ORIGINS,
    IS_PRODUCTION,
    audit_logger,
    dispatch_run,
    limiter,
    reject_prompt_injection,
    reserve_daily_session,
    validate_production_config,
)
from deps import (
    FRONTEND_URL as FRONTEND_URL,  # noqa: F401  (OAuth endpoints below; re-export for tests)
)
from deps import (
    client_key as client_key,  # noqa: F401  (test-facing re-export)
)
from models import (
    AnalysisRun,
    Critic,
    RunEvent,
    SessionStatus,
    SpecSession,
    User,
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
    allow_origins=list(ALLOWED_ORIGINS),
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


# ── Auth payloads ──────────────────────────────────────────────────────────
class SignupPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=100)
    claim_session_id: str | None = None


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class RefreshPayload(BaseModel):
    refresh_token: str


class OAuthCallbackPayload(BaseModel):
    code: str
    redirect_uri: str
    claim_session_id: str | None = None


# ── Auth endpoints ─────────────────────────────────────────────────────────
@app.post("/auth/signup")
@limiter.limit("10/hour")
async def signup(request: Request, payload: SignupPayload):
    with Session(engine) as db:
        existing = db.exec(select(User).where(User.email == payload.email)).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            display_name=payload.display_name or payload.email.split("@")[0],
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Claim guest session if provided
        if payload.claim_session_id:
            try:
                session_id = UUID(payload.claim_session_id)
                session_row = db.get(SpecSession, session_id)
                if session_row and session_row.user_id is None:
                    session_row.user_id = user.id
                    db.add(session_row)
                    db.commit()
            except (ValueError, Exception):
                pass  # Invalid UUID or DB error — skip claim silently

        return {
            "access_token": create_access_token(user.id),
            "refresh_token": create_refresh_token(user.id),
            "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        }


@app.post("/auth/login")
@limiter.limit("10/hour")
async def login(request: Request, payload: LoginPayload):
    with Session(engine) as db:
        user = db.exec(select(User).where(User.email == payload.email)).first()
        if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        return {
            "access_token": create_access_token(user.id),
            "refresh_token": create_refresh_token(user.id),
            "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        }


@app.post("/auth/refresh")
@limiter.limit("30/hour")
async def refresh_token(request: Request, payload: RefreshPayload):
    return rotate_refresh_token(payload.refresh_token)


@app.post("/auth/logout")
@limiter.limit("10/hour")
async def logout(request: Request, payload: RefreshPayload):
    """Revoke every refresh-token family for the token's user (server-side logout)."""
    data = decode_token(payload.refresh_token, expected_type="refresh")
    revoke_user_refresh_tokens(UUID(data["sub"]))
    return {"status": "logged_out"}


@app.get("/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


# ── OAuth: Google ──────────────────────────────────────────────────────────
@app.get("/auth/google")
async def google_redirect():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(501, "Google OAuth not configured")
    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{FRONTEND_URL}/auth/callback?provider=google",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@app.post("/auth/google/callback")
@limiter.limit("10/hour")
async def google_callback(request: Request, payload: OAuthCallbackPayload):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(501, "Google OAuth not configured")
    try:
        info = await exchange_google_code(payload.code, payload.redirect_uri)
    except Exception:
        logger.exception("Google OAuth exchange failed")
        raise HTTPException(400, "Google authentication failed")
    return await _oauth_upsert("google", str(info["id"]), info.get("email", ""), info.get("name", ""), info.get("email_verified", False), payload.claim_session_id)


# ── OAuth: GitHub ──────────────────────────────────────────────────────────
@app.get("/auth/github")
async def github_redirect():
    if not GITHUB_CLIENT_ID:
        raise HTTPException(501, "GitHub OAuth not configured")
    params = urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": f"{FRONTEND_URL}/auth/callback?provider=github",
        "scope": "read:user user:email",
    })
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")


@app.post("/auth/github/callback")
@limiter.limit("10/hour")
async def github_callback(request: Request, payload: OAuthCallbackPayload):
    if not GITHUB_CLIENT_ID:
        raise HTTPException(501, "GitHub OAuth not configured")
    try:
        info = await exchange_github_code(payload.code, payload.redirect_uri)
    except Exception:
        logger.exception("GitHub OAuth exchange failed")
        raise HTTPException(400, "GitHub authentication failed")
    return await _oauth_upsert("github", str(info["id"]), info.get("email", ""), info.get("name") or info.get("login", ""), info.get("email_verified", False), payload.claim_session_id)


async def _oauth_upsert(provider: str, provider_id: str, email: str, display_name: str, email_verified: bool = True, claim_session_id: str | None = None) -> dict:
    """Find or create a user by OAuth provider, return JWT pair.

    The provider identity is always trusted. The *email* is only trusted for
    linking to an existing password account when the provider has verified it;
    otherwise a matching-email link would let anyone hijack that account by
    setting an unverified profile email at the provider.
    """
    if not email_verified:
        audit_logger.warning(
            "oauth_unverified_email_rejected - provider=%s - provider_id=%s", provider, provider_id
        )
        raise HTTPException(400, f"{provider.capitalize()} account email is not verified; verify it at {provider} and try again")
    if not email:
        raise HTTPException(400, f"Could not retrieve email from {provider}")
    with Session(engine) as db:
        user = db.exec(
            select(User).where(User.oauth_provider == provider, User.oauth_provider_id == provider_id)
        ).first()
        if not user:
            # Check if a password-based account exists with the same email
            user = db.exec(select(User).where(User.email == email)).first()
            if user:
                # Link the OAuth provider to the existing account
                user.oauth_provider = provider
                user.oauth_provider_id = provider_id
                if not user.display_name:
                    user.display_name = display_name
            else:
                user = User(
                    email=email,
                    display_name=display_name or email.split("@")[0],
                    oauth_provider=provider,
                    oauth_provider_id=provider_id,
                )
            db.add(user)
            db.commit()
            db.refresh(user)

        # Claim guest session if provided
        if claim_session_id:
            try:
                session_id = UUID(claim_session_id)
                session_row = db.get(SpecSession, session_id)
                if session_row and session_row.user_id is None:
                    session_row.user_id = user.id
                    db.add(session_row)
                    db.commit()
            except Exception:
                logger.warning("Guest-session claim failed for %s", claim_session_id, exc_info=True)

        return {
            "access_token": create_access_token(user.id),
            "refresh_token": create_refresh_token(user.id),
            "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        }


# ── Existing logic (preserved) ─────────────────────────────────────────────
class CreateSession(BaseModel):
    raw_spec: str = Field(min_length=1, max_length=10_000)
    selected_critics: list[Critic] = Field(
        min_length=1,
        default_factory=lambda: [Critic.assumption, Critic.competitor, Critic.economics, Critic.feasibility],
    )

def session_snapshot_events(row: SpecSession):
    """Persistent events replayed to a late WebSocket subscriber."""
    yield {"type": "status", "status": row.status.value}
    yield {"type": "gatekeeper", "missing_context": row.missing_context or []}
    for section, content in row.parsed_sections.items():
        yield {"type": "section_parsed", "section": section, "content": content}
    for finding in row.findings:
        yield {"type": "finding", "finding": finding}
    if row.status == SessionStatus.done:
        yield {"type": "done", "revised_spec": row.revised_spec or ""}


def restart_pipeline_args(row: SpecSession) -> tuple[UUID, str, list[str]]:
    """Compatibility helper retained for callers migrating to durable runs."""
    return row.id, row.raw_spec, row.selected_critics

class ReplyPayload(BaseModel):
    reply: str = Field(min_length=1, max_length=2_000)


@app.post("/sessions")
@limiter.limit("5/hour")
async def create_session(request: Request, payload: CreateSession, user: User | None = Depends(get_optional_user)):
    reject_prompt_injection(payload.raw_spec, request.client.host if request.client else "unknown")
    reserve_daily_session(user)
    selected = [c.value for c in payload.selected_critics]
    row = SpecSession(raw_spec=payload.raw_spec, selected_critics=selected, user_id=user.id if user else None)
    with Session(engine) as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        run = AnalysisRun(session_id=row.id)
        db.add(run)
        db.commit()
        db.refresh(run)

        row_id = row.id
        run_id = run.id

    audit_logger.info("session_created - IP: %s - ID: %s", request.client.host if request.client else "unknown", row_id)

    await dispatch_run(run_id)
    return {"id": row_id, "run_id": run_id}

@app.post("/sessions/{sid}/findings/{fid}/reply")
@limiter.limit("5/minute")
async def reply_to_finding(request: Request, sid: UUID, fid: str, payload: ReplyPayload, user: User | None = Depends(get_optional_user)):
    from sqlalchemy.orm.attributes import flag_modified
    with Session(engine) as db:
        row = db.get(SpecSession, sid)
        if not row:
            raise HTTPException(404, "Session not found")
        if not deps.can_access_session(row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
        if not lifecycle.accepts_client_activity(row.status):
            raise HTTPException(status.HTTP_409_CONFLICT, "Analysis is still in progress for this session")

        finding_dict = next((f for f in row.findings if f.get("id") == fid), None)
        if not finding_dict:
            raise HTTPException(404, "Finding not found")

        finding_dict.setdefault("thread", []).append({"role": "user", "content": payload.reply})
        # Mark the JSON column as dirty so SQLAlchemy detects the in-place mutation
        flag_modified(row, "findings")
        db.add(row)
        db.commit()
        # Capture values while row is still attached to the session
        run = AnalysisRun(session_id=row.id, re_evaluate_finding_id=fid)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

    await dispatch_run(run_id)
    return {"status": "queued", "run_id": str(run_id)}

@app.get("/sessions")
@limiter.limit("30/minute")
async def list_sessions(request: Request, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        if user:
            rows = db.exec(
                select(SpecSession)
                .where(SpecSession.user_id == user.id)
                .order_by(col(SpecSession.created_at).desc())
            ).all()
        else:
            # Guests see no history (their sessions are ephemeral)
            rows = []
    return [
        {
            "id": str(row.id),
            "created_at": row.created_at.isoformat(),
            "status": row.status.value,
            "title": row.raw_spec[:80].split("\n")[0] + ("…" if len(row.raw_spec) > 80 else ""),
        }
        for row in rows
    ]

@app.get("/sessions/{sid}")
@limiter.limit("30/minute")
async def get_session(request: Request, sid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        row = db.get(SpecSession, sid)
    if row is None:
        raise HTTPException(404, "Session not found")
    if not deps.can_access_session(row, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
    return row


@app.post("/sessions/{sid}/stream-ticket")
async def create_stream_ticket(sid: UUID, user: User = Depends(get_current_user)):
    with Session(engine) as db:
        row = db.get(SpecSession, sid)
    if not row:
        raise HTTPException(404, "Session not found")
    if not deps.can_access_session(row, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
    return {"ticket": create_websocket_ticket(user.id)}

@app.websocket("/sessions/{sid}/stream")
async def stream_session(ws: WebSocket, sid: UUID):
    origin = ws.headers.get("origin")
    logger.info("WS connect attempt: sid=%s origin=%s", sid, origin)

    # Validate origin for browser clients (skip if no origin — e.g. non-browser clients)
    if origin and origin not in ALLOWED_ORIGINS:
        logger.warning("WS rejected: origin %s not in ALLOWED_ORIGINS", origin)
        await ws.accept()
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Browser WebSockets cannot send Authorization headers. A short-lived token
    # is supplied as a subprotocol instead of leaking a bearer token in the URL.
    ws_user: User | None = None
    protocols = [item.strip() for item in ws.headers.get("sec-websocket-protocol", "").split(",")]
    ticket = next((item for item in protocols if item.count(".") == 2), None)
    if ticket:
        try:
            payload = decode_token(ticket, expected_type="websocket")
            with Session(engine) as db:
                ws_user = db.get(User, UUID(payload["sub"]))
        except HTTPException:
            pass  # Invalid token → treat as guest

    with Session(engine) as db:
        row = db.get(SpecSession, sid)
    if row and not deps.can_access_session(row, ws_user):
        logger.warning("WS rejected: access denied for session %s", sid)
        await ws.accept()
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept(subprotocol="specadversary" if "specadversary" in protocols else None)
    try:
        # Replay the persisted snapshot for a browser that connects after the
        # very fast stub pipeline (or reconnects after a page reload).
        if row:
            for event in session_snapshot_events(row):
                await ws.send_json(event)
        await _stream_run_events(ws, sid)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass  # client went away or the socket was torn down — nothing to clean up


def _latest_run_id(db: Session, sid: UUID) -> UUID | None:
    latest = db.exec(
        select(AnalysisRun).where(AnalysisRun.session_id == sid).order_by(col(AnalysisRun.created_at).desc())
    ).first()
    return latest.id if latest else None


def _events_after(db: Session, run_id: UUID, after_sequence: int):
    return db.exec(
        select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.sequence > after_sequence).order_by(col(RunEvent.sequence))
    ).all()


async def _send_replay(ws: WebSocket, events) -> int:
    """Replay persisted history; coalesce token deltas so a reconnecting
    client resuming mid-synthesis receives one consolidated snapshot instead
    of duplicated prefix text. Returns the highest sequence delivered."""
    last_sequence = 0
    buffered_tokens = ""
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        last_sequence = max(last_sequence, event.sequence or 0)
        if payload.get("type") == "token":
            buffered_tokens += str(payload.get("content", ""))
            continue
        if buffered_tokens:
            await ws.send_json({"type": "token", "content": buffered_tokens})
            buffered_tokens = ""
        await ws.send_json(payload)
    if buffered_tokens:
        await ws.send_json({"type": "token", "content": buffered_tokens})
    return last_sequence


async def _subscribe_safe(run_id: UUID):
    """Live pub/sub tail; degrade to polling when Redis is unavailable."""
    try:
        return await subscribe_run(run_id)
    except Exception:
        logger.warning("Redis pub/sub unavailable for run %s; using polling fallback", run_id)
        return None


async def _close_pubsub(pubsub) -> None:
    try:
        await pubsub.aclose()
    except Exception:
        logger.warning("Failed to close pub/sub connection", exc_info=True)


async def _stream_run_events(ws: WebSocket, sid: UUID) -> None:
    """Stream events for the session's latest run until the client leaves.

    Delivery is push-first (Redis pub/sub) with a sequence-guarded DB poll as
    both fallback and reconciliation pass — a missed pub/sub message is healed
    by the next poll instead of being lost.
    """
    current_run_id: UUID | None = None
    last_sequence = 0
    pubsub = None
    while True:
        with Session(engine) as db:
            run_id = _latest_run_id(db, sid)

        if run_id != current_run_id:
            current_run_id = run_id
            last_sequence = 0
            if pubsub is not None:
                await _close_pubsub(pubsub)
                pubsub = None
            if run_id is not None:
                pubsub = await _subscribe_safe(run_id)
                with Session(engine) as db:
                    history = _events_after(db, run_id, 0)
                last_sequence = await _send_replay(ws, history)

        if pubsub is not None and run_id is not None:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except Exception:
                logger.exception("Pub/sub receive failed for run %s; falling back to polling", run_id)
                await _close_pubsub(pubsub)
                pubsub = None
                continue
            if message and message.get("type") == "message":
                envelope = json.loads(message["data"])
                if envelope.get("seq", 0) > last_sequence:
                    last_sequence = envelope["seq"]
                    await ws.send_json(envelope["event"])
        else:
            # Polling fallback (no Redis) — also heals any missed pub/sub gap.
            if run_id is not None:
                with Session(engine) as db:
                    fresh = _events_after(db, run_id, last_sequence)
                for event in fresh:
                    payload = event.payload if isinstance(event.payload, dict) else {}
                    await ws.send_json(payload)
                    last_sequence = max(last_sequence, event.sequence or 0)
            await asyncio.sleep(0.5)



app.include_router(risk_routes.router)

