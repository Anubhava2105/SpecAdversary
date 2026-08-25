import os

from sqlmodel import create_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///spec_adversary.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Schema is owned exclusively by Alembic (`alembic upgrade head`, run by the
# container entrypoint before uvicorn starts). Do not call
# SQLModel.metadata.create_all here — drift between models and migrations
# is guarded by tests/test_alembic_consistency.py instead.
