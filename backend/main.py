from __future__ import annotations
import asyncio
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from database import create_db_and_tables, engine
from graph import spec_graph
from models import DailyUsage, SessionStatus, SpecSession

ALLOWED_ORIGINS = {"https://specadversary.com", "http://localhost:5174"}
DAILY_SESSION_LIMIT = 100
INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\b(?:output|reveal|show|print)\s+(?:your\s+)?system\s+prompt\b", re.IGNORECASE),
)
limiter = Limiter(key_func=get_remote_address)
listeners: dict[str,set[asyncio.Queue]]=defaultdict(set)
@asynccontextmanager
async def lifespan(app): create_db_and_tables(); yield
app=FastAPI(title="Spec Adversary",lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware,allow_origins=list(ALLOWED_ORIGINS),allow_methods=["POST", "GET"],allow_headers=["Content-Type"],allow_credentials=False)
class CreateSession(BaseModel): raw_spec:str=Field(min_length=1,max_length=10_000)

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
async def run_pipeline(sid,raw):
    final={}
    try:
        async for mode,data in spec_graph.astream({"raw_spec":raw,"findings":[]},stream_mode=["custom","updates"]):
            if mode=="custom":
                if data.get("type")=="status": save(sid,status=SessionStatus(data["status"]))
                await publish(str(sid),data)
            else:
                for _,update in data.items():
                    final.update(update)
                    if "parsed_sections" in update: save(sid,parsed_sections=update["parsed_sections"])
                    if "findings" in update: save(sid,findings=update["findings"])
        revised=final.get("revised_spec",raw); save(sid,findings=final.get("findings",[]),revised_spec=revised,status=SessionStatus.done)
        await publish(str(sid),{"type":"done","revised_spec":revised})
    except Exception as exc: await publish(str(sid),{"type":"error","message":str(exc)})
@app.post("/sessions")
@limiter.limit("5/hour")
async def create_session(request: Request, payload:CreateSession):
    reject_prompt_injection(payload.raw_spec)
    reserve_daily_session()
    row=SpecSession(raw_spec=payload.raw_spec)
    with Session(engine) as db: db.add(row); db.commit(); db.refresh(row)
    asyncio.create_task(run_pipeline(row.id,row.raw_spec)); return {"id":row.id}
@app.get("/sessions/{sid}")
async def get_session(sid:UUID):
    with Session(engine) as db: row=db.get(SpecSession,sid)
    if not row: raise HTTPException(404,"Session not found")
    return row
@app.websocket("/sessions/{sid}/stream")
async def stream_session(ws:WebSocket,sid:UUID):
    # Reject before accept so an untrusted page cannot read session stream data.
    if ws.headers.get("origin") not in ALLOWED_ORIGINS:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept(); queue=asyncio.Queue(); key=str(sid); listeners[key].add(queue)
    try:
        with Session(engine) as db: row=db.get(SpecSession,sid)
        # Replay the persisted snapshot for a browser that connects after the
        # very fast stub pipeline (or reconnects after a page reload).
        if row:
            await ws.send_json({"type":"status","status":row.status.value})
            for section,content in row.parsed_sections.items(): await ws.send_json({"type":"section_parsed","section":section,"content":content})
            for finding in row.findings: await ws.send_json({"type":"finding","finding":finding})
            if row.status==SessionStatus.done: await ws.send_json({"type":"done","revised_spec":row.revised_spec or ""})
        while True: await ws.send_json(await queue.get())
    except WebSocketDisconnect: pass
    finally: listeners[key].discard(queue)
