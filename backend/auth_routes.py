"""Authentication and OAuth routes: signup, login, token refresh/logout,
provider redirects and callbacks, and the OAuth account-linking upsert."""
from __future__ import annotations

import logging
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Session, select

import deps
from auth import (
    GITHUB_CLIENT_ID,
    GOOGLE_CLIENT_ID,
    create_access_token,
    create_refresh_token,
    decode_token,
    exchange_github_code,
    exchange_google_code,
    get_current_user,
    hash_password,
    revoke_user_refresh_tokens,
    rotate_refresh_token,
    verify_password,
)
from database import engine
from models import SpecSession, User

logger = logging.getLogger(__name__)

router = APIRouter()

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
@router.post("/auth/signup")
@deps.limiter.limit("10/hour")
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


@router.post("/auth/login")
@deps.limiter.limit("10/hour")
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


@router.post("/auth/refresh")
@deps.limiter.limit("30/hour")
async def refresh_token(request: Request, payload: RefreshPayload):
    return rotate_refresh_token(payload.refresh_token)


@router.post("/auth/logout")
@deps.limiter.limit("10/hour")
async def logout(request: Request, payload: RefreshPayload):
    """Revoke every refresh-token family for the token's user (server-side logout)."""
    data = decode_token(payload.refresh_token, expected_type="refresh")
    revoke_user_refresh_tokens(UUID(data["sub"]))
    return {"status": "logged_out"}


@router.get("/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


# ── OAuth: Google ──────────────────────────────────────────────────────────
@router.get("/auth/google")
async def google_redirect():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(501, "Google OAuth not configured")
    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{deps.FRONTEND_URL}/auth/callback?provider=google",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.post("/auth/google/callback")
@deps.limiter.limit("10/hour")
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
@router.get("/auth/github")
async def github_redirect():
    if not GITHUB_CLIENT_ID:
        raise HTTPException(501, "GitHub OAuth not configured")
    params = urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": f"{deps.FRONTEND_URL}/auth/callback?provider=github",
        "scope": "read:user user:email",
    })
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")


@router.post("/auth/github/callback")
@deps.limiter.limit("10/hour")
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
        deps.audit_logger.warning(
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
