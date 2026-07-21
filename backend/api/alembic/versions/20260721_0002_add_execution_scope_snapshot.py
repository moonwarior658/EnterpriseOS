"""add execution scope and recipients snapshot

Revision ID: 20260721_0002
Revises: e39fe5d914eb
Create Date: 2026-07-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260721_0002"
down_revision: Union[str, Sequence[str], None] = "e39fe5d914eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "automation_executions",
        sa.Column(
            "scope_type",
            sa.String(length=32),
            nullable=True,
            server_default="company",
        ),
    )
    op.add_column(
        "automation_executions",
        sa.Column("scope_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "automation_executions",
        sa.Column(
            "recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.execute(
        """
        UPDATE automation_executions AS execution
        SET
            scope_type = COALESCE(
                (
                    SELECT schedule.scope_type
                    FROM automation_schedules AS schedule
                    WHERE schedule.id = execution.schedule_id
                ),
                'company'
            ),
            scope_id = (
                SELECT schedule.scope_id
                FROM automation_schedules AS schedule
                WHERE schedule.id = execution.schedule_id
            ),
            recipients = COALESCE(
                (
                    SELECT schedule.recipients
                    FROM automation_schedules AS schedule
                    WHERE schedule.id = execution.schedule_id
                ),
                '[]'::jsonb
            )
        """
    )

    op.alter_column(
        "automation_executions",
        "scope_type",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "automation_executions",
        "recipients",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("automation_executions", "recipients")
    op.drop_column("automation_executions", "scope_id")
    op.drop_column("automation_executions", "scope_type")
