"""Add RefreshToken table for rotation and reuse detection.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refreshtoken",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("superseded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_refreshtoken_token_hash"),
    )
    op.create_index("ix_refreshtoken_family_id", "refreshtoken", ["family_id"])
    op.create_index("ix_refreshtoken_user_id", "refreshtoken", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_refreshtoken_user_id", table_name="refreshtoken")
    op.drop_index("ix_refreshtoken_family_id", table_name="refreshtoken")
    op.drop_table("refreshtoken")
