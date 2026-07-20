"""Add Gatekeeper persistence and repair session migration drift.

Revision ID: a1b2c3d4e5f6
Revises: 848195252e7e
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "848195252e7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration predates selected_critics even though the runtime
    # model has used it. This forward migration repairs that drift.
    with op.batch_alter_table("specsession") as batch:
        batch.add_column(sa.Column("selected_critics", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("missing_context", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    # SQLite stores the SQLAlchemy enum as text, so the new `moderating`
    # application value requires no destructive table rebuild.


def downgrade() -> None:
    with op.batch_alter_table("specsession") as batch:
        batch.drop_column("missing_context")
        batch.drop_column("selected_critics")
