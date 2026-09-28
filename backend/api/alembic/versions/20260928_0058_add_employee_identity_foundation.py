"""add employee identity foundation

Revision ID: 20260928_0058
Revises: 20260925_0057
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260928_0058"
down_revision: str | None = "20260925_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EMPLOYEE_ROLES = (
    "ADMIN", "DIRECTOR", "DEPUTY_DIRECTOR", "ACCOUNTANT", "SUPPLY_MANAGER",
    "DRIVER", "HANDYMAN", "NETWORK_MANAGER", "CHEF_CONFECTIONER",
    "CONFECTIONER", "BAKER", "HEAD_OF_PRODUCTION", "SELLER",
)


def upgrade() -> None:
    op.add_column("users", sa.Column("account_type", sa.String(16), nullable=False, server_default="HUMAN"))
    op.create_check_constraint("user_account_type", "users", "account_type IN ('HUMAN', 'SERVICE')")
    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("linked_user_id", sa.Integer(), nullable=True),
        sa.Column("full_name", sa.String(240), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("photo_url", sa.String(500), nullable=True),
        sa.Column("phone", sa.String(64), nullable=False),
        sa.Column("residence_address", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("dismissal_date", sa.Date(), nullable=True),
        sa.Column("dismissal_reason", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["linked_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("linked_user_id", name="uq_employees_linked_user_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_employees_tenant_id"),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISMISSED')", name="employee_status"),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND dismissal_date IS NULL AND dismissal_reason IS NULL) "
            "OR (status = 'DISMISSED' AND dismissal_date IS NOT NULL AND length(trim(dismissal_reason)) > 0)",
            name="ck_employees_lifecycle_fields",
        ),
    )
    op.create_index("ix_employees_tenant_status_name", "employees", ["tenant_id", "status", "full_name"])
    op.add_column("users", sa.Column("blocked_by_employee_dismissal", sa.Boolean(), nullable=False, server_default="false"))

    op.create_table(
        "employee_role_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=False),
        sa.Column("ended_reason", sa.String(1000), nullable=True),
        sa.Column("ended_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"], name="fk_employee_role_assignments_employee_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ended_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(f"role IN {EMPLOYEE_ROLES!r}", name="employee_role"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_employee_role_assignment_period"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_employee_role_assignment_reason"),
        sa.CheckConstraint("ended_reason IS NULL OR length(trim(ended_reason)) > 0", name="ck_employee_role_assignment_ended_reason"),
    )
    op.create_index("uq_employee_role_assignments_active", "employee_role_assignments", ["tenant_id", "employee_id", "role"], unique=True, postgresql_where=sa.text("valid_to IS NULL"))

    op.create_table(
        "employee_department_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=False),
        sa.Column("ended_reason", sa.String(1000), nullable=True),
        sa.Column("ended_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"], name="fk_employee_department_assignments_employee_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"], name="fk_employee_department_assignments_department_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ended_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_employee_department_assignment_period"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_employee_department_assignment_reason"),
        sa.CheckConstraint("ended_reason IS NULL OR length(trim(ended_reason)) > 0", name="ck_employee_department_assignment_ended_reason"),
    )
    op.create_index("uq_employee_department_assignments_active_department", "employee_department_assignments", ["tenant_id", "employee_id", "department_id"], unique=True, postgresql_where=sa.text("valid_to IS NULL"))
    op.create_index("uq_employee_department_assignments_active_primary", "employee_department_assignments", ["tenant_id", "employee_id"], unique=True, postgresql_where=sa.text("valid_to IS NULL AND is_primary"))

    op.create_table(
        "employee_lifecycle_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"], name="fk_employee_lifecycle_events_employee_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("event_type IN ('CREATED','UPDATED','DISMISSED','REACTIVATED','USER_LINKED','USER_UNLINKED')", name="employee_lifecycle_event_type"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_employee_lifecycle_events_reason"),
    )
    op.create_index("ix_employee_lifecycle_events_employee", "employee_lifecycle_events", ["tenant_id", "employee_id", "created_at"])


def downgrade() -> None:
    op.drop_table("employee_lifecycle_events")
    op.drop_table("employee_department_assignments")
    op.drop_table("employee_role_assignments")
    op.drop_column("users", "blocked_by_employee_dismissal")
    op.drop_table("employees")
    op.drop_constraint("user_account_type", "users", type_="check")
    op.drop_column("users", "account_type")
