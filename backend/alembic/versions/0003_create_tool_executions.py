"""create tool executions ledger

Revision ID: 0003_create_tool_executions
Revises: 0002_create_approvals
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_create_tool_executions"
down_revision = "0002_create_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("tool_executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=False),
        sa.Column("tool_call_id", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("result_content", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.UniqueConstraint("task_id", "tool_call_id", name="uq_tool_executions_task_call"),
        sa.UniqueConstraint("idempotency_key", name="uq_tool_executions_key"),
        sa.CheckConstraint("status IN ('EXECUTING', 'SUCCEEDED', 'FAILED', 'UNKNOWN')", name="ck_tool_executions_status"),
    )


def downgrade():
    op.drop_table("tool_executions")
