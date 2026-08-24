from __future__ import annotations
import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import UUID
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import text
from sqlmodel import Session, select
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from database import create_db_and_tables, engine
from models import AnalysisRun, Critic, DailyUsage, Risk, RiskComment, RiskStatus, RunEvent, RunStatus, SessionStatus, SpecSession, User
from broker import enqueue_run
from pipeline_runner import execute_run
from risk_service import (
    backfill_risks_for_session,
    get_risk_summary,
    upsert_risks_from_findings,
    validate_status_transition,
)
from auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, create_websocket_ticket, decode_token,
    get_optional_user, get_current_user,
    revoke_user_refresh_tokens, rotate_refresh_token,
    exchange_google_code, exchange_github_code,
    GOOGLE_CLIENT_ID, GITHUB_CLIENT_ID,
)

logger = logging.getLogger(__name__)

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
DAILY_SESSION_LIMIT = 100
INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\b(?:output|reveal|show|print)\s+(?:your\s+)?system\s+prompt\b", re.IGNORECASE),
)
limiter = Limiter(key_func=get_remote_address)
# For reverse proxies, typically slowapi uses X-Forwarded-For if properly configured with proxy middleware, but we'll leave it simple.
inline_tasks: set[asyncio.Task] = set()
audit_logger = logging.getLogger("audit")

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
                headers = dict(message.get("headers", []))
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"x-xss-protection", b"1; mode=block"),
                ]
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)

@asynccontextmanager
async def lifespan(app):
    validate_production_config()
    create_db_and_tables()
    yield
app=FastAPI(title="Spec Adversary",lifespan=lifespan, docs_url=None if os.environ.get("ENV") == "production" else "/docs")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.add_middleware(SecurityHeadersMiddleware)


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
            except (ValueError, Exception):
                pass

        return {
            "access_token": create_access_token(user.id),
            "refresh_token": create_refresh_token(user.id),
            "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        }


# ── Session ownership helpers ──────────────────────────────────────────────
def _can_access_session(session_row: SpecSession, user: User | None) -> bool:
    """Guest sessions (user_id=None) are open. Owned sessions require the matching user."""
    if session_row.user_id is None:
        return True
    return user is not None and session_row.user_id == user.id


# ── Existing logic (preserved) ─────────────────────────────────────────────
class CreateSession(BaseModel):
    raw_spec: str = Field(min_length=1, max_length=10_000)
    selected_critics: list[Critic] = Field(
        default_factory=lambda: [Critic.assumption, Critic.competitor, Critic.economics, Critic.feasibility]
    )

def reject_prompt_injection(raw_spec: str, client_ip: str) -> None:
    """Reject obvious instruction-override attempts before they reach an LLM."""
    if any(pattern.search(raw_spec) for pattern in INJECTION_PATTERNS):
        audit_logger.warning("prompt_injection_blocked - IP: %s - Preview: %s", client_ip, raw_spec[:200])
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Spec contains a disallowed prompt-injection phrase")

def reserve_daily_session() -> None:
    """Atomically reserve one of today's SQLite-backed session budget slots."""
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
    reserve_daily_session()
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
        if not _can_access_session(row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

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
                .order_by(SpecSession.created_at.desc())
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
    with Session(engine) as db: row=db.get(SpecSession,sid)
    if not row: raise HTTPException(404,"Session not found")
    if not _can_access_session(row, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
    return row


@app.post("/sessions/{sid}/stream-ticket")
async def create_stream_ticket(sid: UUID, user: User = Depends(get_current_user)):
    with Session(engine) as db:
        row = db.get(SpecSession, sid)
    if not row:
        raise HTTPException(404, "Session not found")
    if not _can_access_session(row, user):
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
    if row and not _can_access_session(row, ws_user):
        logger.warning("WS rejected: access denied for session %s", sid)
        await ws.accept()
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept(subprotocol="specadversary" if "specadversary" in protocols else None)
    last_event_id = 0
    try:
        # Replay the persisted snapshot for a browser that connects after the
        # very fast stub pipeline (or reconnects after a page reload).
        if row:
            for event in session_snapshot_events(row):
                await ws.send_json(event)
        while True:
            with Session(engine) as db:
                latest_run = db.exec(select(AnalysisRun).where(AnalysisRun.session_id == sid).order_by(AnalysisRun.created_at.desc())).first()
                events = [] if latest_run is None else db.exec(
                    select(RunEvent).where(RunEvent.run_id == latest_run.id, RunEvent.id > last_event_id).order_by(RunEvent.id)
                ).all()
            for event in events:
                await ws.send_json(event.payload)
                last_event_id = event.id or last_event_id
            await asyncio.sleep(0.25)
    except (WebSocketDisconnect, asyncio.CancelledError): pass


# ── Risk Register payloads ─────────────────────────────────────────────────
class RiskPatchPayload(BaseModel):
    status: str | None = None
    validation_plan: str | None = Field(default=None, max_length=5000)
    owner_id: str | None = None  # "self" or null to unassign
    due_date: str | None = None  # ISO 8601 or null to clear
    confidence: int | None = Field(default=None, ge=0, le=100)


class RiskCommentPayload(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class RiskCommentResponse(BaseModel):
    id: str
    risk_id: str
    author_id: str | None
    author_email: str | None = None
    body: str
    created_at: str


class RiskResponse(BaseModel):
    id: str
    session_id: str
    finding_id: str | None
    critic: str
    severity: str
    claim: str
    critique: str
    suggested_fix: str | None
    confidence: int | None
    evidence: list[dict] | None
    validation_plan: str | None
    status: str
    owner_id: str | None
    owner_email: str | None = None
    due_date: str | None
    source_run_id: str | None
    created_at: str
    updated_at: str
    resolved_at: str | None
    comments: list[RiskCommentResponse] | None = None


class RiskSummaryResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    overdue: int
    unassigned: int


class RiskListResponse(BaseModel):
    items: list[RiskResponse]
    total: int
    summary: RiskSummaryResponse


def _risk_to_response(risk: Risk, *, comments: list[RiskCommentResponse] | None = None, owner_email: str | None = None) -> RiskResponse:
    return RiskResponse(
        id=str(risk.id),
        session_id=str(risk.session_id),
        finding_id=risk.finding_id,
        critic=risk.critic,
        severity=risk.severity,
        claim=risk.claim,
        critique=risk.critique,
        suggested_fix=risk.suggested_fix,
        confidence=risk.confidence,
        evidence=risk.evidence or [],
        validation_plan=risk.validation_plan,
        status=risk.status if isinstance(risk.status, str) else risk.status.value,
        owner_id=str(risk.owner_id) if risk.owner_id else None,
        owner_email=owner_email,
        due_date=risk.due_date.isoformat() if risk.due_date else None,
        source_run_id=str(risk.source_run_id) if risk.source_run_id else None,
        created_at=risk.created_at.isoformat(),
        updated_at=risk.updated_at.isoformat(),
        resolved_at=risk.resolved_at.isoformat() if risk.resolved_at else None,
        comments=comments,
    )


# ── Risk Register endpoints ───────────────────────────────────────────────
@app.get("/sessions/{sid}/risks")
@limiter.limit("30/minute")
async def list_risks(
    request: Request,
    sid: UUID,
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = None,
    critic: str | None = None,
    search: str | None = None,
    sort_by: str = "severity",
    sort_dir: str = "desc",
    offset: int = 0,
    limit: int = 50,
    user: User | None = Depends(get_optional_user),
):
    with Session(engine) as db:
        session_row = db.get(SpecSession, sid)
        if not session_row:
            raise HTTPException(404, "Session not found")
        if not _can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        # Lazy backfill for legacy sessions
        backfill_risks_for_session(sid)

        query = select(Risk).where(Risk.session_id == sid)
        if status_filter:
            query = query.where(Risk.status == status_filter)
        if severity:
            query = query.where(Risk.severity == severity)
        if critic:
            query = query.where(Risk.critic == critic)
        if search:
            query = query.where(Risk.claim.contains(search))

        # Sorting
        SORT_COLUMNS = {
            "severity": Risk.severity,
            "created_at": Risk.created_at,
            "updated_at": Risk.updated_at,
            "due_date": Risk.due_date,
            "status": Risk.status,
        }
        sort_col = SORT_COLUMNS.get(sort_by, Risk.severity)
        query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

        all_risks = db.exec(query).all()
        total = len(all_risks)
        paginated = all_risks[offset : offset + limit]

        items = [_risk_to_response(r) for r in paginated]

    summary = get_risk_summary(sid)
    return RiskListResponse(items=items, total=total, summary=RiskSummaryResponse(**summary))


@app.get("/sessions/{sid}/risk-summary")
@limiter.limit("30/minute")
async def risk_summary(request: Request, sid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        session_row = db.get(SpecSession, sid)
        if not session_row:
            raise HTTPException(404, "Session not found")
        if not _can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        backfill_risks_for_session(sid)
        summary = get_risk_summary(sid)

    return RiskSummaryResponse(**summary)


@app.get("/risks/{rid}")
@limiter.limit("30/minute")
async def get_risk_detail(request: Request, rid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        risk = db.get(Risk, rid)
        if not risk:
            raise HTTPException(404, "Risk not found")
        session_row = db.get(SpecSession, risk.session_id)
        if not session_row or not _can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        comments_rows = db.exec(
            select(RiskComment).where(RiskComment.risk_id == rid).order_by(RiskComment.created_at)
        ).all()
        comments = []
        for c in comments_rows:
            author_email = None
            if c.author_id:
                author = db.get(User, c.author_id)
                author_email = author.email if author else None
            comments.append(RiskCommentResponse(
                id=str(c.id),
                risk_id=str(c.risk_id),
                author_id=str(c.author_id) if c.author_id else None,
                author_email=author_email,
                body=c.body,
                created_at=c.created_at.isoformat(),
            ))

        owner_email = None
        if risk.owner_id:
            owner = db.get(User, risk.owner_id)
            owner_email = owner.email if owner else None

        return _risk_to_response(risk, comments=comments, owner_email=owner_email)


@app.patch("/risks/{rid}")
@limiter.limit("30/minute")
async def patch_risk(request: Request, rid: UUID, payload: RiskPatchPayload, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        risk = db.get(Risk, rid)
        if not risk:
            raise HTTPException(404, "Risk not found")
        session_row = db.get(SpecSession, risk.session_id)
        if not session_row or not _can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        # Status transition
        if payload.status is not None:
            try:
                new_status = RiskStatus(payload.status)
            except ValueError:
                raise HTTPException(400, f"Invalid status: {payload.status}")
            old_status = RiskStatus(risk.status) if isinstance(risk.status, str) else risk.status
            if not validate_status_transition(old_status, new_status):
                raise HTTPException(
                    400,
                    f"Cannot transition from '{old_status.value}' to '{new_status.value}'"
                )
            risk.status = new_status.value
            # Auto-manage resolved_at
            if new_status == RiskStatus.resolved:
                risk.resolved_at = datetime.now(timezone.utc)
            elif old_status == RiskStatus.resolved:
                risk.resolved_at = None

        # Validation plan
        if payload.validation_plan is not None:
            risk.validation_plan = payload.validation_plan

        # Owner assignment — auth-only per user decision
        if payload.owner_id is not None:
            if payload.owner_id == "self":
                if user is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required to assign ownership")
                risk.owner_id = user.id
            elif payload.owner_id == "":
                risk.owner_id = None
            else:
                raise HTTPException(400, "owner_id must be 'self' or empty string to unassign")

        # Due date
        if payload.due_date is not None:
            if payload.due_date == "":
                risk.due_date = None
            else:
                try:
                    risk.due_date = datetime.fromisoformat(payload.due_date)
                except ValueError:
                    raise HTTPException(400, "Invalid due_date format (use ISO 8601)")

        # Confidence
        if payload.confidence is not None:
            risk.confidence = payload.confidence

        risk.updated_at = datetime.now(timezone.utc)
        db.add(risk)
        db.commit()
        db.refresh(risk)

        owner_email = None
        if risk.owner_id:
            owner = db.get(User, risk.owner_id)
            owner_email = owner.email if owner else None

        return _risk_to_response(risk, owner_email=owner_email)


@app.post("/risks/{rid}/comments")
@limiter.limit("30/minute")
async def add_risk_comment(request: Request, rid: UUID, payload: RiskCommentPayload, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        risk = db.get(Risk, rid)
        if not risk:
            raise HTTPException(404, "Risk not found")
        session_row = db.get(SpecSession, risk.session_id)
        if not session_row or not _can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        comment = RiskComment(
            risk_id=rid,
            author_id=user.id if user else None,
            body=payload.body,
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)

        author_email = user.email if user else None
        return RiskCommentResponse(
            id=str(comment.id),
            risk_id=str(comment.risk_id),
            author_id=str(comment.author_id) if comment.author_id else None,
            author_email=author_email,
            body=comment.body,
            created_at=comment.created_at.isoformat(),
        )


@app.post("/risks/{rid}/re-evaluate")
@limiter.limit("5/minute")
async def re_evaluate_risk(request: Request, rid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db:
        risk = db.get(Risk, rid)
        if not risk:
            raise HTTPException(404, "Risk not found")
        session_row = db.get(SpecSession, risk.session_id)
        if not session_row or not _can_access_session(session_row, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")

        if not risk.finding_id:
            raise HTTPException(400, "Cannot re-evaluate a risk without a finding_id")

        run = AnalysisRun(session_id=risk.session_id, re_evaluate_finding_id=risk.finding_id)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

    await dispatch_run(run_id)
    return {"status": "queued", "run_id": str(run_id)}
