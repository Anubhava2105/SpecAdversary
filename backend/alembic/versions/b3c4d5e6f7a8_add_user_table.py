"""add user table and session user_id FK

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-07-21 11:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create user table
    op.create_table(
        "user",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=False, server_default=""),
        sa.Column("oauth_provider", sa.String(), nullable=True),
        sa.Column("oauth_provider_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    # Add user_id FK to specsession — nullable so existing guest rows stay valid
    op.add_column("specsession", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_specsession_user", "specsession", "user", ["user_id"], ["id"])
    op.create_index("ix_specsession_user_id", "specsession", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_specsession_user_id", table_name="specsession")
    op.drop_constraint("fk_specsession_user", "specsession", type_="foreignkey")
    op.drop_column("specsession", "user_id")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")
