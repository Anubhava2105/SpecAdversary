"""Add Risk Register tables.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("specsession.id"), nullable=False),
        sa.Column("finding_id", sa.String(), nullable=True),
        sa.Column("critic", sa.String(), nullable=False, server_default=""),
        sa.Column("severity", sa.String(), nullable=False, server_default=""),
        sa.Column("claim", sa.String(), nullable=False, server_default=""),
        sa.Column("critique", sa.String(), nullable=False, server_default=""),
        sa.Column("suggested_fix", sa.String(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("validation_plan", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("source_run_id", sa.Uuid(), sa.ForeignKey("analysisrun.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("session_id", "finding_id", name="uq_risk_session_finding"),
    )
    op.create_index("ix_risk_session_id", "risk", ["session_id"])
    op.create_index("ix_risk_status", "risk", ["status"])
    op.create_index("ix_risk_owner_id", "risk", ["owner_id"])
    op.create_index("ix_risk_due_date", "risk", ["due_date"])

    op.create_table(
        "riskcomment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("risk_id", sa.Uuid(), sa.ForeignKey("risk.id"), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("body", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_riskcomment_risk_id", "riskcomment", ["risk_id"])


def downgrade() -> None:
    op.drop_index("ix_riskcomment_risk_id", table_name="riskcomment")
    op.drop_table("riskcomment")
    op.drop_index("ix_risk_due_date", table_name="risk")
    op.drop_index("ix_risk_owner_id", table_name="risk")
    op.drop_index("ix_risk_status", table_name="risk")
    op.drop_index("ix_risk_session_id", table_name="risk")
    op.drop_table("risk")
