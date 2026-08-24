"""Authentication: password hashing, JWT tokens, FastAPI dependencies, OAuth helpers."""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlmodel import Session, select

from database import engine
from models import RefreshToken, User

# ── Config ──────────────────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7
WEBSOCKET_TICKET_EXPIRE_SECONDS = 60

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

# ── Password hashing ───────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ─────────────────────────────────────────────────────────────────────
def create_access_token(user_id: UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "type": "access", "jti": str(uuid4()), "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def create_refresh_token(user_id: UUID, family_id: UUID | None = None) -> str:
    """Issue a refresh token and persist its hash so it can be rotated and revoked."""
    family_id = family_id or uuid4()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    token = jwt.encode(
        {"sub": str(user_id), "type": "refresh", "jti": str(uuid4()), "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with Session(engine) as db:
        db.add(RefreshToken(
            family_id=family_id,
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=expire,
        ))
        db.commit()
    return token


def rotate_refresh_token(token: str) -> dict:
    """Consume a refresh token, return a fresh access/refresh pair.

    Presenting an already-superseded token means either a stolen token or a
    broken client; both cases revoke the entire family to fail closed.
    """
    payload = decode_token(token, expected_type="refresh")
    digest = hash_token(token)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        row = db.exec(select(RefreshToken).where(RefreshToken.token_hash == digest)).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown refresh token")
        if row.revoked or (row.expires_at and row.expires_at.replace(tzinfo=timezone.utc) < now):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

        if row.superseded:
            family = db.exec(
                select(RefreshToken).where(RefreshToken.family_id == row.family_id)
            ).all()
            for member in family:
                member.revoked = True
                db.add(member)
            db.commit()
            logging.getLogger("audit").warning(
                "refresh_token_reuse_detected - user=%s - family=%s", row.user_id, row.family_id
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token reuse detected; all sessions were revoked. Please sign in again.",
            )

        row.superseded = True
        db.add(row)
        db.commit()
        user_id, family_id = row.user_id, row.family_id

    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id, family_id=family_id),
    }


def revoke_user_refresh_tokens(user_id: UUID) -> None:
    """Revoke every live refresh-token family belonging to the user."""
    with Session(engine) as db:
        rows = db.exec(
            select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked == False)  # noqa: E712
        ).all()
        for row in rows:
            row.revoked = True
            db.add(row)
        db.commit()


def hash_token(token: str) -> str:
    """Only hashes of tokens are persisted — a DB leak cannot mint sessions."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_websocket_ticket(user_id: UUID) -> str:
    """A short-lived, single-purpose credential safe for the WebSocket handshake."""
    expire = datetime.now(timezone.utc) + timedelta(seconds=WEBSOCKET_TICKET_EXPIRE_SECONDS)
    return jwt.encode(
        {"sub": str(user_id), "type": "websocket", "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str, expected_type: str = "access") -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")
    return payload


# ── FastAPI dependencies ────────────────────────────────────────────────────
bearer_scheme = HTTPBearer(auto_error=False)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> User | None:
    """Returns the authenticated user, or None for guest access."""
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials, expected_type="access")
    with Session(engine) as db:
        user = db.get(User, UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_user(
    user: User | None = Depends(get_optional_user),
) -> User:
    """Requires authentication. Raises 401 if no valid token."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


# ── OAuth helpers ───────────────────────────────────────────────────────────
async def exchange_google_code(code: str, redirect_uri: str) -> dict:
    """Exchange Google OAuth authorization code for user info.

    Returns {"id", "email", "name", "email_verified"}; Google always reports
    whether it has verified the address.
    """
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        user_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_resp.raise_for_status()
        info = user_resp.json()  # {"id", "email", "verified_email", ...}
        return {
            "id": info["id"],
            "email": info.get("email", ""),
            "name": info.get("name", ""),
            "email_verified": bool(info.get("verified_email")),
        }


async def exchange_github_code(code: str, redirect_uri: str) -> dict:
    """Exchange GitHub OAuth authorization code for user info.

    The email is resolved to the primary AND verified address; unverified
    addresses are never trusted for account linking.
    """
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "code": code,
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()

        # GitHub doesn't return email in /user; resolve via /user/emails and
        # accept only an address that is both primary and verified.
        emails_resp = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        emails_resp.raise_for_status()
        primary = next(
            (e for e in emails_resp.json() if e.get("primary") and e.get("verified")),
            None,
        )
        user_data["email"] = primary["email"] if primary else None
        user_data["email_verified"] = primary is not None

        return {
            "id": user_data["id"],
            "email": user_data["email"],
            "name": user_data.get("name") or user_data.get("login", ""),
            "login": user_data.get("login", ""),
            "email_verified": user_data["email_verified"],
        }
