"""add automation runtime status

Revision ID: 20260722_0004
Revises: 20260722_0003
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0004"
down_revision: Union[str, Sequence[str], None] = "20260722_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automation_runtime_status",
        sa.Column("component_key", sa.String(length=32), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id_safe", sa.String(length=32), nullable=True),
        sa.Column("poll_interval_seconds", sa.Float(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scanned", sa.Integer(), nullable=True),
        sa.Column("claimed", sa.Integer(), nullable=True),
        sa.Column("created", sa.Integer(), nullable=True),
        sa.Column("failed", sa.Integer(), nullable=True),
        sa.Column("skipped", sa.Integer(), nullable=True),
        sa.Column("configured", sa.Boolean(), nullable=True),
        sa.Column("reachable", sa.Boolean(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("safe_message", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "component_key IN ('worker', 'scheduler', 'n8n')",
            name="ck_automation_runtime_status_component",
        ),
        sa.PrimaryKeyConstraint("component_key"),
    )


def downgrade() -> None:
    op.drop_table("automation_runtime_status")
