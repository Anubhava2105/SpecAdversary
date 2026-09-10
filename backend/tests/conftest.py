"""Shared test setup: one in-memory engine installed before app code imports.

Test modules previously rebound database.engine per-module, but main,
risk_service, and auth bind ``from database import engine`` at their own
first import — leaving them pointed at a different DB than the fixtures.
conftest.py is imported by pytest before any test module, so installing
the engine here keeps every consumer on the same connection.
"""
import os

# Hermetic suite: app modules call load_dotenv() at import, so a developer's
# backend/.env leaks into the test process. DEV_NO_LIMITS=true disables rate
# limiting and daily budgets, which silently inverts budget assertions
# (reserve_daily_session early-returns); INLINE_WORKER=true would execute
# real pipelines inline during tests. Scrub both before any app import; the
# per-test fixture below re-scrubs them for every test. Tests that need a
# flag set it explicitly via monkeypatch (auto-undone after the test).
for _leaked in ("DEV_NO_LIMITS", "INLINE_WORKER"):
    os.environ.pop(_leaked, None)
del _leaked

from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from db import database

# Always run the suite against throwaway in-memory SQLite. A file-backed
# default URL would leak rows between runs and break uniqueness assertions.
database.engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

import db.models  # noqa: E402, F401  (populate SQLModel metadata against shared engine)
from db.database import engine  # noqa: E402

SQLModel.metadata.create_all(engine)
with engine.begin() as conn:
    conn.execute(
        text("CREATE TABLE IF NOT EXISTS daily_usage (day TEXT PRIMARY KEY, sessions_created INTEGER)")
    )


import pytest  # noqa: E402


@pytest.fixture
def db_engine():
    """The single shared test engine installed above."""
    return engine


@pytest.fixture(autouse=True)
def _hermetic_env():
    """Re-scrub the local-dev escape hatch for every test.

    Regression guard: without this, DEV_NO_LIMITS=true leaking from a
    developer's backend/.env disables budget enforcement mid-suite and
    turns limit tests red (or worse, silently green for the wrong reason).
    """
    import os

    for _leaked in ("DEV_NO_LIMITS", "INLINE_WORKER"):
        os.environ.pop(_leaked, None)
    yield
    for _leaked in ("DEV_NO_LIMITS", "INLINE_WORKER"):
        os.environ.pop(_leaked, None)


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch):
    """Stub the dispatch seam for every test: no test may touch Redis.

    Module-level `deps.dispatch_run = ...` assignments used to leak across
    modules (import-time rebinding is permanent and order-dependent).
    Tests for dispatch itself monkeypatch over this stub.
    """
    from core import deps as _deps

    async def _noop(run_id):
        return None

    monkeypatch.setattr(_deps, "dispatch_run", _noop)


@pytest.fixture(autouse=True)
def _no_rate_limiting():
    """Disable slowapi for every test instead of each module mutating
    ``main.limiter`` post-import."""
    import main

    previous = main.limiter.enabled
    main.limiter.enabled = False
    yield
    main.limiter.enabled = previous
