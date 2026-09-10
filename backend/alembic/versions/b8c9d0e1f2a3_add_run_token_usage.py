"""Add AnalysisRun.token_usage for per-run cost visibility.

Revision ID: b8c9d0e1f2a3
Revises: f7a8b9c0d1e2
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2a3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysisrun", sa.Column("token_usage", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysisrun", "token_usage")
