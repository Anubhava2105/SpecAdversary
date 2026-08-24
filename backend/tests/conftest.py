"""Shared test setup: one in-memory engine installed before app code imports.

Test modules previously rebound database.engine per-module, but main,
risk_service, and auth bind ``from database import engine`` at their own
first import — leaving them pointed at a different DB than the fixtures.
conftest.py is imported by pytest before any test module, so installing
the engine here keeps every consumer on the same connection.
"""
import database
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

# Always run the suite against throwaway in-memory SQLite. A file-backed
# default URL would leak rows between runs and break uniqueness assertions.
database.engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

import models  # noqa: E402  (populate SQLModel metadata against shared engine)
from database import engine  # noqa: E402

SQLModel.metadata.create_all(engine)
with engine.begin() as conn:
    conn.execute(
        text("CREATE TABLE IF NOT EXISTS daily_usage (day TEXT PRIMARY KEY, sessions_created INTEGER)")
    )
