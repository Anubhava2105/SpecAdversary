"""The session-and-run lifecycle: the single owner of legal status movement.

Every SessionStatus and RunStatus transition in the system flows through this
module. It owns three things:

1. The legality table (which transitions may happen, including idempotent
   same-status writes).
2. Transition side effects (timestamps on runs, cascade from a failed run to
   its in-flight session).
3. The shape of the status events published to WebSocket subscribers.

Callers keep transaction scope: they pass ORM objects, this module mutates
them, and the caller commits. That keeps the module testable with plain
in-memory objects and lets different callers batch differently (the reaper
commits many runs at once; execute_run commits per step).

Domain terms are defined in CONTEXT.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db.models import RunStatus, SessionStatus


class IllegalTransition(Exception):
    """Raised when a status change is not permitted by the legality table."""


# Forward stage progression of an analysis. Failure is reachable from every
# state; terminal states re-enter parsing only via explicit re-run (re-evaluate
# or retry).
_FORWARD: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.parsing: {SessionStatus.critiquing},
    SessionStatus.critiquing: {SessionStatus.moderating},
    SessionStatus.moderating: {SessionStatus.synthesizing},
    SessionStatus.synthesizing: {SessionStatus.done},
}

_IN_FLIGHT = set(_FORWARD)
_TERMINAL_RUN_STATUSES = {RunStatus.succeeded, RunStatus.failed, RunStatus.cancelled}


def accepts_client_activity(status: SessionStatus) -> bool:
    """May clients mutate this session's findings/risks right now?

    False while an analysis is in flight; true once it is done or failed.
    The single home for the vocabulary shared by the reply and re-evaluate
    guards.
    """
    return status not in _IN_FLIGHT


def ingest_status(raw: Any) -> SessionStatus:
    """Validate a raw status name arriving over the graph event stream.

    Graph nodes emit plain strings; this is the one place that decides which
    names exist. Unknown or malformed values raise ValueError so bad events
    fail loudly instead of silently corrupting session state.
    """
    try:
        return SessionStatus(str(raw))
    except ValueError as exc:
        raise ValueError(f"Unknown session status emitted by pipeline: {raw!r}") from exc


def status_events(status: SessionStatus) -> list[dict[str, str]]:
    """The publication payloads announcing a session's new status."""
    return [{"type": "status", "status": status.value}]


def transition_session(session, to: SessionStatus, **extra_fields) -> list[dict[str, str]]:
    """Move a session to *to*, applying side effects; return events to publish.

    Mutates the passed ORM object (caller commits). Raises IllegalTransition
    without mutating anything if the move is not legal. Same-status writes are
    legal and idempotent. Extra keyword arguments (findings, revised_spec, ...)
    are applied alongside the status so a state change and its payload land in
    one mutation.
    """
    current = session.status
    if not _session_transition_legal(current, to):
        raise IllegalTransition(f"Illegal session transition: {current.value} -> {to.value}")

    session.status = to
    for key, value in extra_fields.items():
        setattr(session, key, value)
    return status_events(to)


def transition_run(
    run,
    to: RunStatus,
    cascade_session=None,
    at: datetime | None = None,
    **extra_fields,
) -> list[dict[str, str]]:
    """Move a run to *to*; optionally cascade failure into its session.

    Sets started_at when entering `running` and finished_at on any terminal
    status (both derived from *at*, defaulting to now — callers with an
    injected clock pass it through). When *cascade_session* is given and the
    run fails, the session is also moved to failed — but only while it is
    still in flight, so reaping a stale orphaned run never corrupts a session
    that already finished. Returns the status events a caller should publish.
    """
    now = at or datetime.now(timezone.utc)
    run.status = to
    if to is RunStatus.running:
        run.started_at = now
    if to in _TERMINAL_RUN_STATUSES:
        run.finished_at = now
    for key, value in extra_fields.items():
        setattr(run, key, value)

    events: list[dict[str, str]] = []
    if cascade_session is not None and to is RunStatus.failed and cascade_session.status in _IN_FLIGHT:
        transition_session(cascade_session, SessionStatus.failed)
        events.extend(status_events(cascade_session.status))
    return events


def _session_transition_legal(current: SessionStatus, to: SessionStatus) -> bool:
    if current == to:
        return True  # idempotent write
    if to is SessionStatus.failed:
        return True  # anything can fail
    # An analysis that finishes successfully marks the session done from
    # whichever stage it reached: short pipelines (e.g. the stub flow) complete
    # without visiting every critic stage.
    if current in _IN_FLIGHT and to is SessionStatus.done:
        return True
    if to in _FORWARD.get(current, set()):
        return True  # forward stage progression
    if current in (SessionStatus.done, SessionStatus.failed) and to is SessionStatus.parsing:
        return True  # explicit re-run: re-evaluate or retry
    return False
