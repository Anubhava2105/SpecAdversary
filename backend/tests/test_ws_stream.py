"""Tests for WebSocket event streaming: snapshot, coalesced replay, ordering."""
import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session

import main
from core import deps
from db.database import engine
from db.models import AnalysisRun, RunEvent, RunStatus, SpecSession

deps.dispatch_run = lambda run_id: asyncio.sleep(0)
client = TestClient(main.app)


def _make_session_with_history() -> str:
    """A finished session whose run has interleaved token/other events."""
    with Session(engine) as db:
        row = SpecSession(raw_spec="spec text", status="done", revised_spec="Hello brave world")
        db.add(row)
        db.commit()
        db.refresh(row)

        run = AnalysisRun(session_id=row.id, status=RunStatus.succeeded)
        db.add(run)
        db.commit()
        db.refresh(run)

        events = [
            ("status", {"type": "status", "status": "parsing"}),
            ("token", {"type": "token", "content": "Hello "}),
            ("token", {"type": "token", "content": "brave "}),
            ("finding", {"type": "finding", "finding": {"id": "f1"}}),
            ("token", {"type": "token", "content": "world"}),
            ("done", {"type": "done", "revised_spec": "Hello brave world"}),
        ]
        for i, (event_type, payload) in enumerate(events, start=1):
            db.add(RunEvent(
                run_id=run.id,
                sequence=i,
                type=event_type,
                payload=payload,
                created_at=datetime.now(timezone.utc),
            ))
        db.commit()
        return str(row.id)


def test_replay_coalesces_token_deltas_and_preserves_order():
    sid = _make_session_with_history()
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        # Snapshot: session status + gatekeeper + done (session is finished)
        first = ws.receive_json()
        assert first["type"] == "status"
        second = ws.receive_json()
        assert second["type"] == "gatekeeper"
        snapshot_done = ws.receive_json()
        assert snapshot_done["type"] == "done"

        # History replay: tokens coalesce up to each non-token boundary
        third = ws.receive_json()    # status (history seq 1)
        assert third == {"type": "status", "status": "parsing"}
        assert ws.receive_json() == {"type": "token", "content": "Hello brave "}
        finding = ws.receive_json()
        assert finding == {"type": "finding", "finding": {"id": "f1"}}
        assert ws.receive_json() == {"type": "token", "content": "world"}
        done = ws.receive_json()
        assert done == {"type": "done", "revised_spec": "Hello brave world"}


def test_stream_closes_cleanly_on_client_disconnect():
    sid = _make_session_with_history()
    with client.websocket_connect(f"/sessions/{sid}/stream") as ws:
        for _ in range(8):
            ws.receive_json()
    # Exiting the context closes the socket; server must not error.
