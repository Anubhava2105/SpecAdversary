"""Direct tests for the Ownership Rule's own interface (core.ownership).

Route tests reach the rule indirectly; these target the seam itself:
guest-open, owner-only, and every 404/403 edge of both helpers.
"""
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from core import ownership
from db.database import engine
from db.models import Risk, SpecSession, User


def _user() -> User:
    return User(id=uuid4(), email="owner@example.com")


def test_guest_sessions_are_open_to_anyone():
    row = SimpleNamespace(user_id=None)
    assert ownership.can_access_session(row, None) is True
    assert ownership.can_access_session(row, _user()) is True


def test_owned_sessions_are_closed_to_everyone_but_owner():
    owner = _user()
    row = SimpleNamespace(user_id=owner.id)
    assert ownership.can_access_session(row, owner) is True
    assert ownership.can_access_session(row, None) is False
    assert ownership.can_access_session(row, _user()) is False


def test_require_session_access_missing_session_is_404():
    with Session(engine) as db:
        with pytest.raises(HTTPException) as exc:
            ownership.require_session_access(db, uuid4(), None)
    assert exc.value.status_code == 404


def test_require_session_access_foreign_owner_is_403():
    owner = _user()
    session_id = uuid4()
    with Session(engine) as db:
        db.add(SpecSession(id=session_id, user_id=owner.id, raw_spec="owned"))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            ownership.require_session_access(db, session_id, _user())
    assert exc.value.status_code == 403


def test_require_session_access_owner_and_guest_pass():
    owner = _user()
    owned_id, open_id = uuid4(), uuid4()
    with Session(engine) as db:
        db.add(SpecSession(id=owned_id, user_id=owner.id, raw_spec="owned"))
        db.add(SpecSession(id=open_id, user_id=None, raw_spec="open"))
        db.commit()
        assert ownership.require_session_access(db, owned_id, owner).id == owned_id
        assert ownership.require_session_access(db, open_id, None).id == open_id


def test_require_risk_access_missing_risk_is_404():
    with Session(engine) as db:
        with pytest.raises(HTTPException) as exc:
            ownership.require_risk_access(db, uuid4(), None)
    assert exc.value.status_code == 404


def test_require_risk_access_returns_both_rows_and_enforces_owner():
    owner = _user()
    session_id = uuid4()
    with Session(engine) as db:
        db.add(SpecSession(id=session_id, user_id=owner.id, raw_spec="owned"))
        db.commit()
        risk = Risk(session_id=session_id, finding_id="f1", critic="assumption",
                    severity="minor", claim="c", critique="q")
        db.add(risk)
        db.commit()
        db.refresh(risk)
        risk_id, sid = risk.id, risk.session_id
        found, session_row = ownership.require_risk_access(db, risk_id, owner)
        assert found.id == risk_id and session_row.id == sid
        with pytest.raises(HTTPException) as exc:
            ownership.require_risk_access(db, risk_id, None)
    assert exc.value.status_code == 403


def test_risk_on_missing_session_is_denied_not_leaked():
    with Session(engine) as db:
        risk = Risk(session_id=uuid4(), finding_id="orphan", critic="assumption",
                    severity="minor", claim="c", critique="q")
        db.add(risk)
        db.commit()
        db.refresh(risk)
        with pytest.raises(HTTPException) as exc:
            ownership.require_risk_access(db, risk.id, None)
    assert exc.value.status_code == 403


def test_deps_reexport_keeps_existing_import_sites_working():
    from core import deps

    assert deps.require_session_access is ownership.require_session_access
    assert deps.require_risk_access is ownership.require_risk_access
    assert deps.can_access_session is ownership.can_access_session
    assert len({UUID(str(uuid4()))}) == 1  # sanity: uuid plumbing intact
