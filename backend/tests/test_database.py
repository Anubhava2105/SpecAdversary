"""Tests for database engine pool configuration (db.database)."""
import db.database as database_module


def test_sqlite_keeps_single_threaded_setup(monkeypatch):
    monkeypatch.setattr(database_module, "DATABASE_URL", "sqlite:///test.db")
    assert database_module._pool_options() == {"connect_args": {"check_same_thread": False}}


def test_postgres_gets_production_pool(monkeypatch):
    monkeypatch.setattr(database_module, "DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "600")
    assert database_module._pool_options() == {
        "pool_size": 7,
        "max_overflow": 3,
        "pool_recycle": 600,
        "pool_pre_ping": True,
    }


def test_postgres_pool_defaults_are_production_sane(monkeypatch):
    monkeypatch.setattr(database_module, "DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    for var in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_RECYCLE_SECONDS"):
        monkeypatch.delenv(var, raising=False)
    assert database_module._pool_options() == {
        "pool_size": 20,
        "max_overflow": 10,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }
