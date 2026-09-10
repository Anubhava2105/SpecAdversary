"""Transactional email: verification links and password resets.

Two backends, chosen by configuration:
- SMTP (stdlib `smtplib`) when SMTP_HOST is set — works with any provider
  offering an SMTP relay (Resend, SendGrid, Mailgun, self-hosted).
- Log backend otherwise: the message is logged and appended to `outbox`,
  so local development and tests can retrieve links without credentials.

Only hashes of tokens ever leave this process toward the database; the raw
token travels exclusively inside the emailed link.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "SpecAdversary <noreply@specadversary.com>")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

# Dev/test aid: every message sent through the log backend lands here.
# Tests should monkeypatch `send_email`, not read this; it exists so a
# developer without SMTP credentials can still complete the flows by hand.
outbox: list[dict] = []


def _smtp_configured() -> bool:
    return bool(SMTP_HOST)


def send_email(to: str, subject: str, body: str) -> None:
    """Send one transactional message, via SMTP or the log fallback."""
    if not _smtp_configured():
        logger.info("Email (log backend) to=%s subject=%s\n%s", to, subject, body)
        outbox.append({"to": to, "subject": subject, "body": body})
        return
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as client:
        if SMTP_USE_TLS:
            client.starttls()
        if SMTP_USERNAME:
            client.login(SMTP_USERNAME, SMTP_PASSWORD)
        client.send_message(msg)
    logger.info("Email sent to=%s subject=%s", to, subject)


def verification_link(token: str) -> str:
    from core import deps

    return f"{deps.FRONTEND_URL}/verify-email?token={token}"


def reset_link(token: str) -> str:
    from core import deps

    return f"{deps.FRONTEND_URL}/reset-password?token={token}"


def send_verification_email(to: str, token: str) -> None:
    send_email(
        to,
        "Verify your SpecAdversary email",
        "Confirm this address to finish securing your account:\n\n"
        f"{verification_link(token)}\n\n"
        "The link expires in 24 hours. If you did not sign up, ignore this message.",
    )


def send_reset_email(to: str, token: str) -> None:
    send_email(
        to,
        "Reset your SpecAdversary password",
        "Someone requested a password reset for this address:\n\n"
        f"{reset_link(token)}\n\n"
        "The link expires in 1 hour and works once. If that was not you, ignore this message.",
    )
