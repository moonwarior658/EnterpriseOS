"""add iiko employee links and personal shifts

Revision ID: 20260928_0059
Revises: 20260928_0058
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260928_0059"
down_revision: str | None = "20260928_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "iiko_employee_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_user_id", sa.String(160), nullable=False),
        sa.Column("iiko_display_name", sa.String(240), nullable=False),
        sa.Column("iiko_birth_date", sa.Date(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("ended_reason", sa.String(1000), nullable=True),
        sa.Column("ended_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_iiko_employee_links_employee_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ended_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_iiko_employee_link_period"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_iiko_employee_link_reason"),
        sa.CheckConstraint("ended_reason IS NULL OR length(trim(ended_reason)) > 0", name="ck_iiko_employee_link_ended_reason"),
    )
    op.create_index(
        "uq_iiko_employee_links_active_employee", "iiko_employee_links",
        ["tenant_id", "employee_id"], unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "uq_iiko_employee_links_active_user", "iiko_employee_links",
        ["tenant_id", "iiko_user_id"], unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "ix_iiko_employee_links_history", "iiko_employee_links",
        ["tenant_id", "employee_id", "valid_from"],
    )

    op.create_table(
        "employee_iiko_shifts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_user_id", sa.String(160), nullable=False),
        sa.Column("external_shift_id", sa.String(160), nullable=True),
        sa.Column("iiko_department_id", sa.String(160), nullable=True),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="IIKO"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("raw_external_idempotency_key", sa.String(255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_employee_iiko_shifts_employee_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"],
            name="fk_employee_iiko_shifts_department_tenant", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "raw_external_idempotency_key", name="uq_employee_iiko_shifts_idempotency"),
        sa.CheckConstraint("source = 'IIKO'", name="ck_employee_iiko_shift_source"),
        sa.CheckConstraint("status IN ('OPEN','CLOSED')", name="employee_iiko_shift_status"),
        sa.CheckConstraint("closed_at IS NULL OR closed_at >= opened_at", name="ck_employee_iiko_shift_period"),
        sa.CheckConstraint("(status = 'OPEN' AND closed_at IS NULL AND duration_minutes IS NULL) OR (status = 'CLOSED' AND closed_at IS NOT NULL AND duration_minutes IS NOT NULL)", name="ck_employee_iiko_shift_status"),
    )
    op.create_index(
        "ix_employee_iiko_shifts_employee_opened", "employee_iiko_shifts",
        ["tenant_id", "employee_id", "opened_at"],
    )
    op.create_index(
        "uq_employee_iiko_shifts_active_employee", "employee_iiko_shifts",
        ["tenant_id", "employee_id"], unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )


def downgrade() -> None:
    op.drop_table("employee_iiko_shifts")
    op.drop_table("iiko_employee_links")
