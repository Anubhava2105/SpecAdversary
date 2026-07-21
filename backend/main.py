from __future__ import annotations
import asyncio
import logging
import os
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import UUID
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
from graph import spec_graph
from models import Critic, DailyUsage, SessionStatus, SpecSession, User
from auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_optional_user, get_current_user,
    exchange_google_code, exchange_github_code,
    GOOGLE_CLIENT_ID, GITHUB_CLIENT_ID,
)

logger = logging.getLogger(__name__)

ALLOWED_ORIGINS = {os.getenv("CORS_ORIGIN", "https://specadversary.com"), "http://localhost:5174"}
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5174")
DAILY_SESSION_LIMIT = 100
INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\b(?:output|reveal|show|print)\s+(?:your\s+)?system\s+prompt\b", re.IGNORECASE),
)
limiter = Limiter(key_func=get_remote_address)
listeners: dict[str,set[asyncio.Queue]]=defaultdict(set)
running_pipelines: set[str] = set()
@asynccontextmanager
async def lifespan(app): create_db_and_tables(); yield
app=FastAPI(title="Spec Adversary",lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware,allow_origins=list(ALLOWED_ORIGINS),allow_methods=["POST", "GET"],allow_headers=["Content-Type", "Authorization"],allow_credentials=True)


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
async def refresh_token(payload: RefreshPayload):
    data = decode_token(payload.refresh_token, expected_type="refresh")
    user_id = UUID(data["sub"])
    with Session(engine) as db:
        user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }


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
    except Exception as exc:
        logger.exception("Google OAuth exchange failed")
        raise HTTPException(400, "Google authentication failed")
    return await _oauth_upsert("google", str(info["id"]), info.get("email", ""), info.get("name", ""), payload.claim_session_id)


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
    except Exception as exc:
        logger.exception("GitHub OAuth exchange failed")
        raise HTTPException(400, "GitHub authentication failed")
    return await _oauth_upsert("github", str(info["id"]), info.get("email", ""), info.get("name") or info.get("login", ""), payload.claim_session_id)


async def _oauth_upsert(provider: str, provider_id: str, email: str, display_name: str, claim_session_id: str | None) -> dict:
    """Find or create a user by OAuth provider, return JWT pair."""
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

def reject_prompt_injection(raw_spec: str) -> None:
    """Reject obvious instruction-override attempts before they reach an LLM."""
    if any(pattern.search(raw_spec) for pattern in INJECTION_PATTERNS):
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
async def publish(sid,event):
    for queue in list(listeners[sid]): await queue.put(event)
def save(sid,**values):
    with Session(engine) as db:
        row=db.get(SpecSession,sid)
        if row:
            for key,value in values.items(): setattr(row,key,value)
            db.add(row); db.commit()

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
    return row.id, row.raw_spec, row.selected_critics
async def run_pipeline(sid, raw, selected_critics=None, re_evaluate_finding_id=None):
    key = str(sid)
    if key in running_pipelines:
        return   # already running
    running_pipelines.add(key)
    final = {}
    try:
        initial_state = {"raw_spec": raw, "findings": []}
        if selected_critics:
            initial_state["selected_critics"] = selected_critics
            
        if re_evaluate_finding_id:
            with Session(engine) as db: 
                row = db.get(SpecSession, sid)
            if row:
                initial_state["existing_findings"] = row.findings
                initial_state["parsed_sections"] = row.parsed_sections
            initial_state["re_evaluate_finding_id"] = re_evaluate_finding_id
            
        async for mode, data in spec_graph.astream(initial_state, stream_mode=["custom", "updates"]):
            if mode == "custom":
                if data.get("type") == "status":
                    save(sid, status=SessionStatus(data["status"]))
                await publish(key, data)
            else:
                for _, update in data.items():
                    final.update(update)
                    if "parsed_sections" in update:
                        save(sid, parsed_sections=update["parsed_sections"])
                    if "missing_context" in update:
                        save(sid, missing_context=update["missing_context"])
                    if "findings" in update:
                        save(sid, findings=update["findings"])
                    if "moderated_findings" in update:
                        save(sid, findings=update["moderated_findings"])
        revised = final.get("revised_spec", raw)
        authoritative_findings = final.get("moderated_findings", final.get("findings", []))
        save(sid, findings=authoritative_findings, revised_spec=revised, status=SessionStatus.done)
        await publish(key, {"type": "done", "revised_spec": revised})
    except Exception as exc:
        logger.exception("Pipeline failed for session %s", sid)
        await publish(key, {"type": "error", "message": "Analysis failed. Please try again."})
    finally:
        running_pipelines.discard(key)


class ReplyPayload(BaseModel):
    reply: str = Field(min_length=1, max_length=2_000)


@app.post("/sessions")
@limiter.limit("5/hour")
async def create_session(request: Request, payload: CreateSession, user: User | None = Depends(get_optional_user)):
    reject_prompt_injection(payload.raw_spec)
    reserve_daily_session()
    selected = [c.value for c in payload.selected_critics]
    row = SpecSession(raw_spec=payload.raw_spec, selected_critics=selected, user_id=user.id if user else None)
    with Session(engine) as db: db.add(row); db.commit(); db.refresh(row)
    asyncio.create_task(run_pipeline(row.id, row.raw_spec, selected))
    return {"id": row.id}

@app.post("/sessions/{sid}/findings/{fid}/reply")
@limiter.limit("5/minute")
async def reply_to_finding(request: Request, sid: UUID, fid: str, payload: ReplyPayload, user: User | None = Depends(get_optional_user)):
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
    save(sid, findings=row.findings)
    
    asyncio.create_task(run_pipeline(row.id, row.raw_spec, row.selected_critics, re_evaluate_finding_id=fid))
    return {"status": "ok"}

@app.get("/sessions")
async def list_sessions(user: User | None = Depends(get_optional_user)):
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
async def get_session(sid: UUID, user: User | None = Depends(get_optional_user)):
    with Session(engine) as db: row=db.get(SpecSession,sid)
    if not row: raise HTTPException(404,"Session not found")
    if not _can_access_session(row, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
    return row

@app.websocket("/sessions/{sid}/stream")
async def stream_session(ws: WebSocket, sid: UUID, token: str | None = Query(default=None)):
    # Validate origin for browser clients
    if ws.headers.get("origin") not in ALLOWED_ORIGINS:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Validate ownership via token query param
    ws_user: User | None = None
    if token:
        try:
            payload = decode_token(token, expected_type="access")
            with Session(engine) as db:
                ws_user = db.get(User, UUID(payload["sub"]))
        except HTTPException:
            pass  # Invalid token → treat as guest

    with Session(engine) as db:
        row = db.get(SpecSession, sid)
    if row and not _can_access_session(row, ws_user):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept(); queue=asyncio.Queue(); key=str(sid); listeners[key].add(queue)
    try:
        # Replay the persisted snapshot for a browser that connects after the
        # very fast stub pipeline (or reconnects after a page reload).
        if row:
            for event in session_snapshot_events(row):
                await ws.send_json(event)
            if row.status != SessionStatus.done and key not in running_pipelines:
                # Pipeline died (e.g. backend restart) — re-launch it.
                asyncio.create_task(run_pipeline(*restart_pipeline_args(row)))
        while True: await ws.send_json(await queue.get())
    except WebSocketDisconnect: pass
    finally: listeners[key].discard(queue)
