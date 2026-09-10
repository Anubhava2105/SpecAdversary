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

from core import deps
from core.auth import (
    EMAIL_TOKEN_RESET,
    EMAIL_TOKEN_VERIFY,
    GITHUB_CLIENT_ID,
    GOOGLE_CLIENT_ID,
    RESET_TOKEN_TTL,
    VERIFY_TOKEN_TTL,
    consume_email_token,
    create_access_token,
    create_email_token,
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
from core.email import send_reset_email, send_verification_email
from db.database import engine
from db.models import SpecSession, User

logger = logging.getLogger(__name__)

router = APIRouter()


def _normalize_email(email: str) -> str:
    """Lowercase + strip: `Victim@x.com` and `victim@x.com` are one account.

    Lookups are case-sensitive at the DB, so every read and write path goes
    through here or duplicate accounts bypass the verified-email link.
    """
    return email.strip().lower()


def _token_pair(user: User) -> dict:
    """The JWT access/refresh pair plus public user shape returned at every sign-in."""
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "email_verified": user.email_verified,
        },
    }


def _send_verification(user_id, email: str) -> None:
    """Issue a verification token and email the link. Best-effort by design:
    SMTP outages must never fail signup — the resend endpoint covers retries."""
    try:
        token = create_email_token(user_id, EMAIL_TOKEN_VERIFY, VERIFY_TOKEN_TTL)
        send_verification_email(email, token)
    except Exception:
        logger.exception("Verification email failed for %s", email)


def _claim_guest_session(db: Session, user_id, claim_session_id: str | None) -> None:
    """Attach an unowned guest session to a fresh sign-in.

    Claiming is proof-of-identifier only; the silent skip on bad input is
    intentional (a stale client-sent id must not fail signup).
    """
    if not claim_session_id:
        return
    try:
        session_id = UUID(claim_session_id)
        session_row = db.get(SpecSession, session_id)
        if session_row and session_row.user_id is None:
            session_row.user_id = user_id
            db.add(session_row)
            db.commit()
    except Exception:
        logger.warning("Guest-session claim failed for %s", claim_session_id, exc_info=True)


async def _exchange_oauth(provider_display: str, exchange, code: str, redirect_uri: str) -> dict:
    """Run a provider code exchange, translating any failure into a 400."""
    try:
        return await exchange(code, redirect_uri)
    except Exception:
        logger.exception("%s OAuth exchange failed", provider_display)
        raise HTTPException(400, f"{provider_display} authentication failed")

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
    email = _normalize_email(payload.email)
    with Session(engine) as db:
        existing = db.exec(select(User).where(User.email == email)).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
        user = User(
            email=email,
            password_hash=hash_password(payload.password),
            display_name=payload.display_name or email.split("@")[0],
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        _claim_guest_session(db, user.id, payload.claim_session_id)

        _send_verification(user.id, user.email)

        return _token_pair(user)


@router.post("/auth/login")
@deps.limiter.limit("10/hour")
async def login(request: Request, payload: LoginPayload):
    with Session(engine) as db:
        user = db.exec(select(User).where(User.email == _normalize_email(payload.email))).first()
        if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        return _token_pair(user)


@router.post("/auth/refresh")
@deps.limiter.limit("30/hour")
async def refresh_token(request: Request, payload: RefreshPayload):
    return rotate_refresh_token(payload.refresh_token)


@router.post("/auth/logout")
@deps.limiter.limit("10/hour")
async def logout(request: Request, payload: RefreshPayload):
    """Revoke every refresh-token family for the token's user (server-side logout).

    Expiry is not verified: an expired-but-legitimate token must still log the
    user out. The signature is always verified, so the `sub` is trustworthy.
    """
    data = decode_token(payload.refresh_token, expected_type="refresh", verify_exp=False)
    revoke_user_refresh_tokens(UUID(data["sub"]))
    return {"status": "logged_out"}


@router.get("/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "email_verified": user.email_verified,
    }


class ForgotPasswordPayload(BaseModel):
    email: EmailStr


class ResetPasswordPayload(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class VerifyEmailPayload(BaseModel):
    token: str = Field(min_length=16, max_length=128)


@router.post("/auth/forgot-password")
@deps.limiter.limit("5/hour")
async def forgot_password(request: Request, payload: ForgotPasswordPayload):
    """Start a password reset. Always 200: the response must not reveal
    whether an address is registered (user-enumeration guard)."""
    email = _normalize_email(payload.email)
    with Session(engine) as db:
        user = db.exec(select(User).where(User.email == email)).first()
        if user is not None and user.password_hash is not None:
            token = create_email_token(user.id, EMAIL_TOKEN_RESET, RESET_TOKEN_TTL)
            try:
                send_reset_email(user.email, token)
            except Exception:
                logger.exception("Reset email failed for %s", email)
            deps.audit_logger.info("password_reset_requested - user=%s", user.id)
    return {"status": "ok"}


@router.post("/auth/reset-password")
@deps.limiter.limit("10/hour")
async def reset_password(request: Request, payload: ResetPasswordPayload):
    """Redeem a reset token for a new password. Single-use: consume marks
    the token, and every refresh family is revoked so stolen sessions die."""
    user_id = consume_email_token(payload.token, EMAIL_TOKEN_RESET)
    with Session(engine) as db:
        user = db.get(User, user_id)
        if user is None or user.password_hash is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        user.password_hash = hash_password(payload.password)
        db.add(user)
        db.commit()
    revoke_user_refresh_tokens(user_id)
    deps.audit_logger.info("password_reset_completed - user=%s", user_id)
    return {"status": "ok"}


@router.post("/auth/verify-email")
@deps.limiter.limit("30/hour")
async def verify_email(request: Request, payload: VerifyEmailPayload):
    """Redeem a verification token. Idempotent: re-verifying a verified
    address still returns ok (mail clients prefetch links)."""
    user_id = consume_email_token(payload.token, EMAIL_TOKEN_VERIFY)
    with Session(engine) as db:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        user.email_verified = True
        db.add(user)
        db.commit()
    deps.audit_logger.info("email_verified - user=%s", user_id)
    return {"status": "ok"}


@router.post("/auth/resend-verification")
@deps.limiter.limit("5/hour")
async def resend_verification(request: Request, user: User = Depends(get_current_user)):
    if not user.email_verified:
        _send_verification(user.id, user.email)
    return {"status": "ok"}


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
    info = await _exchange_oauth("Google", exchange_google_code, payload.code, payload.redirect_uri)
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
    info = await _exchange_oauth("GitHub", exchange_github_code, payload.code, payload.redirect_uri)
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
    email = _normalize_email(email)
    with Session(engine) as db:
        user = db.exec(
            select(User).where(User.oauth_provider == provider, User.oauth_provider_id == provider_id)
        ).first()
        if not user:
            # Check if a password-based account exists with the same email
            user = db.exec(select(User).where(User.email == email)).first()
            if user:
                if user.oauth_provider and user.oauth_provider != provider:
                    # A second provider must not silently orphan the first
                    # link — the user has to unlink it explicitly.
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"This account is already linked to {user.oauth_provider}; unlink it first",
                    )
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
            # The provider verified this address (unverified raises above),
            # so OAuth accounts skip the email-verification flow entirely.
            user.email_verified = True
            db.add(user)
            db.commit()
            db.refresh(user)

        _claim_guest_session(db, user.id, claim_session_id)

        return _token_pair(user)
