"""add shift department confirmations

Revision ID: 20260929_0060
Revises: 20260928_0059
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260929_0060"
down_revision: str | None = "20260928_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_employee_iiko_shifts_tenant_id",
        "employee_iiko_shifts",
        ["tenant_id", "id"],
    )
    op.create_table(
        "shift_department_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("shift_id", sa.Uuid(), nullable=False),
        sa.Column("primary_department_id", sa.Uuid(), nullable=False),
        sa.Column("actual_department_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_shift_department_confirmations_employee_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "shift_id"], ["employee_iiko_shifts.tenant_id", "employee_iiko_shifts.id"],
            name="fk_shift_department_confirmations_shift_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "primary_department_id"], ["departments.tenant_id", "departments.id"],
            name="fk_shift_department_confirmations_primary_department_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actual_department_id"], ["departments.tenant_id", "departments.id"],
            name="fk_shift_department_confirmations_actual_department_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "tenant_id", "shift_id", "employee_id",
            name="uq_shift_department_confirmations_shift_employee",
        ),
    )
    op.create_index(
        "ix_shift_department_confirmations_employee_confirmed",
        "shift_department_confirmations",
        ["tenant_id", "employee_id", "confirmed_at"],
    )


def downgrade() -> None:
    op.drop_table("shift_department_confirmations")
    op.drop_constraint(
        "uq_employee_iiko_shifts_tenant_id",
        "employee_iiko_shifts",
        type_="unique",
    )
