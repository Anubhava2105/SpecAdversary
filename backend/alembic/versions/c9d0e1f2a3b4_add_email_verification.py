"""Add User.email_verified and the EmailToken table (verify/reset flows).

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""
from alembic import op
import sqlalchemy as sa

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user") as batch:
        batch.add_column(sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "emailtoken",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_emailtoken_token_hash"),
    )
    op.create_index("ix_emailtoken_user_id", "emailtoken", ["user_id"])
    op.create_index("ix_emailtoken_purpose", "emailtoken", ["purpose"])
    op.create_index("ix_emailtoken_token_hash", "emailtoken", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_emailtoken_token_hash", table_name="emailtoken")
    op.drop_index("ix_emailtoken_purpose", table_name="emailtoken")
    op.drop_index("ix_emailtoken_user_id", table_name="emailtoken")
    op.drop_table("emailtoken")
    with op.batch_alter_table("user") as batch:
        batch.drop_column("email_verified")
