"""The run-stream engine: WebSocket handshake with origin checks and
subprotocol tickets, persisted-event replay, and push-first delivery with a
sequence-guarded polling heal."""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlmodel import Session, col, select

import deps
from auth import decode_token
from broker import subscribe_run
from database import engine
from models import AnalysisRun, RunEvent, SpecSession, User
from session_routes import session_snapshot_events

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/sessions/{sid}/stream")
async def stream_session(ws: WebSocket, sid: UUID):
    origin = ws.headers.get("origin")
    logger.info("WS connect attempt: sid=%s origin=%s", sid, origin)

    # Validate origin for browser clients (skip if no origin — e.g. non-browser clients)
    if origin and origin not in deps.ALLOWED_ORIGINS:
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
