import os

from sqlmodel import create_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///spec_adversary.db")


def _pool_options() -> dict:
    """Production pool tuning for server-side databases.

    SQLAlchemy defaults (pool size 5, no recycle, no pre-ping) drop idle
    connections behind cloud load balancers / managed Postgres, surfacing
    as unhandled 500s. These knobs are env-driven so the single-VM deploy
    and local development can differ without code changes. SQLite keeps a
    plain single-threaded setup (no pooling semantics apply).
    """
    if DATABASE_URL.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
        # Recycle connections before infrastructure idle-timeouts kill them.
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")),
        # Validate connections on checkout: stale pooled connections are
        # discarded instead of raising on first use.
        "pool_pre_ping": True,
    }


engine = create_engine(DATABASE_URL, **_pool_options())

# Schema is owned exclusively by Alembic (`alembic upgrade head`, run by the
# release/migration step before web/worker processes start). Do not call
# SQLModel.metadata.create_all here — drift between models and migrations
# is guarded by tests/test_alembic_consistency.py instead.
