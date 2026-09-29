"""correct iiko personal shift contract

Revision ID: 20260929_0062
Revises: 20260929_0061
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260929_0062"
down_revision: str | None = "20260929_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "iiko_department_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("iiko_department_id", sa.Uuid(), nullable=False),
        sa.Column("eos_department_id", sa.Uuid(), nullable=False),
        sa.Column("source_name", sa.String(240), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "iiko_department_id",
            name="uq_iiko_department_mappings_tenant_external",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "eos_department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_iiko_department_mappings_department_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_iiko_department_mappings_reason",
        ),
    )
    op.drop_constraint(
        "uq_employee_iiko_shifts_idempotency",
        "employee_iiko_shifts",
        type_="unique",
    )
    op.alter_column(
        "employee_iiko_shifts",
        "raw_external_idempotency_key",
        new_column_name="reconciliation_key",
        existing_type=sa.String(255),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_employee_iiko_shifts_reconciliation",
        "employee_iiko_shifts",
        ["tenant_id", "reconciliation_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_employee_iiko_shifts_reconciliation",
        "employee_iiko_shifts",
        type_="unique",
    )
    op.alter_column(
        "employee_iiko_shifts",
        "reconciliation_key",
        new_column_name="raw_external_idempotency_key",
        existing_type=sa.String(255),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_employee_iiko_shifts_idempotency",
        "employee_iiko_shifts",
        ["tenant_id", "raw_external_idempotency_key"],
    )
    op.drop_table("iiko_department_mappings")
