"""add append-only schedule audit log

Revision ID: 20260722_0003
Revises: 20260721_0002
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260722_0003"
down_revision: Union[str, Sequence[str], None] = "20260721_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automation_schedule_audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'automation_schedule_created', "
            "'automation_schedule_updated', "
            "'automation_schedule_enabled', "
            "'automation_schedule_disabled', "
            "'automation_schedule_run_requested'"
            ")",
            name="automation_schedule_audit_event_type",
        ),
        sa.CheckConstraint(
            "schedule_id > 0",
            name="ck_automation_schedule_audit_schedule_id_positive",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_automation_schedule_audit_schedule_occurred",
        "automation_schedule_audit_events",
        ["schedule_id", "occurred_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_automation_schedule_audit_schedule_occurred",
        table_name="automation_schedule_audit_events",
    )
    op.drop_table("automation_schedule_audit_events")
