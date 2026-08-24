import os
from sqlmodel import SQLModel, create_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///spec_adversary.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

def create_db_and_tables() -> None:
    # Retained as a fallback; Alembic is the primary migration path.
    SQLModel.metadata.create_all(engine)
