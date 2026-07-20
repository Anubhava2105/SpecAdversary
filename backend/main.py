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
from models import Critic, DailyUsage, SessionStatus, SpecSession

ALLOWED_ORIGINS = {"https://specadversary.com", "http://localhost:5174"}
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
app.add_middleware(CORSMiddleware,allow_origins=list(ALLOWED_ORIGINS),allow_methods=["POST", "GET"],allow_headers=["Content-Type"],allow_credentials=False)
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
        await publish(key, {"type": "error", "message": str(exc)})
    finally:
        running_pipelines.discard(key)
@app.post("/sessions")
@limiter.limit("5/hour")
async def create_session(request: Request, payload: CreateSession):
    reject_prompt_injection(payload.raw_spec)
    reserve_daily_session()
    selected = [c.value for c in payload.selected_critics]
    row = SpecSession(raw_spec=payload.raw_spec, selected_critics=selected)
    with Session(engine) as db: db.add(row); db.commit(); db.refresh(row)
    asyncio.create_task(run_pipeline(row.id, row.raw_spec, selected))
    return {"id": row.id}

class ReplyPayload(BaseModel):
    reply: str

@app.post("/sessions/{sid}/findings/{fid}/reply")
@limiter.limit("5/minute")
async def reply_to_finding(request: Request, sid: UUID, fid: str, payload: ReplyPayload):
    with Session(engine) as db:
        row = db.get(SpecSession, sid)
    if not row:
        raise HTTPException(404, "Session not found")
        
    finding_dict = next((f for f in row.findings if f.get("id") == fid), None)
    if not finding_dict:
        raise HTTPException(404, "Finding not found")
        
    finding_dict.setdefault("thread", []).append({"role": "user", "content": payload.reply})
    save(sid, findings=row.findings)
    
    asyncio.create_task(run_pipeline(row.id, row.raw_spec, row.selected_critics, re_evaluate_finding_id=fid))
    return {"status": "ok"}

@app.get("/sessions")
async def list_sessions():
    with Session(engine) as db:
        rows = db.query(SpecSession).order_by(SpecSession.created_at.desc()).all()
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
            for event in session_snapshot_events(row):
                await ws.send_json(event)
            if row.status != SessionStatus.done and key not in running_pipelines:
                # Pipeline died (e.g. backend restart) — re-launch it.
                asyncio.create_task(run_pipeline(*restart_pipeline_args(row)))
        while True: await ws.send_json(await queue.get())
    except WebSocketDisconnect: pass
    finally: listeners[key].discard(queue)
