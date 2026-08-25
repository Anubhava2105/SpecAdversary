"""add moderating to sessionstatus enum

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-31 20:15:00.000000
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL enums are strict types; the gatekeeper migration skipped this
    # because it targeted SQLite.  We now add the missing 'moderating' value.
    # SQLite stores statuses as plain VARCHARs, so there is nothing to alter.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS 'moderating' AFTER 'critiquing'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from an existing enum type
    # without recreating it.  This is intentionally left as a no-op because
    # the value is harmless if unused.
    pass
