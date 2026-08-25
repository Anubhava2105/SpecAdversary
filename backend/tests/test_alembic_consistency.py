"""Guard against drift between the SQLModel metadata and Alembic migrations.

Schema ownership is Alembic-only in production (the container entrypoint runs
`alembic upgrade head`; app startup no longer calls create_all). If a model
change lands without a migration, this test fails by comparing:

1. the table/column sets produced by replaying all migrations on a fresh
   throwaway SQLite database, against
2. the table/column sets declared on ``SQLModel.metadata``.
"""
import os

from alembic.config import Config
from sqlalchemy import inspect
from sqlmodel import SQLModel

import models  # noqa: F401  (populates SQLModel.metadata)
from alembic import command

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _schema_of(inspector) -> dict[str, set[str]]:
    return {
        table: {col["name"] for col in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }


def test_migrations_match_model_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    url = f"sqlite:///{db_path}"

    # env.py honours DATABASE_URL over alembic.ini, so pin it explicitly:
    # a developer's backend/.env must not redirect the throwaway database.
    monkeypatch.setenv("DATABASE_URL", url)

    cfg = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    command.upgrade(cfg, "head")

    migrated = _schema_of(inspect(__import__("sqlalchemy").create_engine(url)))
    declared = {
        table: {col.name for col in SQLModel.metadata.tables[table].columns}
        for table in SQLModel.metadata.tables
    }

    missing_tables = declared.keys() - migrated.keys()
    extra_tables = migrated.keys() - declared.keys() - {"alembic_version"}
    assert not missing_tables, f"tables in models but not in migrations: {sorted(missing_tables)}"
    assert not extra_tables, f"tables in migrations but not in models: {sorted(extra_tables)}"

    for table, columns in declared.items():
        missing_cols = columns - migrated[table]
        extra_cols = migrated[table] - columns
        assert not missing_cols, f"{table}: columns missing from migrations: {sorted(missing_cols)}"
        assert not extra_cols, f"{table}: columns in migrations but not in models: {sorted(extra_cols)}"
