"""Add durable analysis runs and replayable run events.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""
from alembic import op
import sqlalchemy as sa

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS 'failed'")
    op.create_table(
        "analysisrun",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("specsession.id"), nullable=False),
        sa.Column("status", sa.Enum("queued", "running", "succeeded", "failed", "cancelled", name="runstatus"), nullable=False),
        sa.Column("re_evaluate_finding_id", sa.String(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_analysisrun_session_id", "analysisrun", ["session_id"])
    op.create_table(
        "runevent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("analysisrun.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),
    )
    op.create_index("ix_runevent_run_id", "runevent", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_runevent_run_id", table_name="runevent")
    op.drop_table("runevent")
    op.drop_index("ix_analysisrun_session_id", table_name="analysisrun")
    op.drop_table("analysisrun")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS runstatus")
