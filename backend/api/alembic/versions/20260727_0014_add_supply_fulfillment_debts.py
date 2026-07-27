"""add supply fulfillment and department debts

Revision ID: 20260727_0014
Revises: 20260727_0013
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0014"
down_revision: Union[str, Sequence[str], None] = "20260727_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "supply_requests",
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column("fulfilled_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_supply_requests_fulfilled_by_user_id_users",
        "supply_requests", "users", ["fulfilled_by_user_id"], ["id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "supply_line_allocations",
        sa.Column(
            "fulfilled_quantity", sa.Numeric(18, 3),
            server_default="0", nullable=False,
        ),
    )
    op.add_column(
        "supply_line_allocations",
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "supply_line_allocations",
        sa.Column("fulfilled_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "supply_line_allocations",
        sa.Column("fulfillment_comment", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_supply_line_allocations_fulfilled_quantity",
        "supply_line_allocations",
        "fulfilled_quantity >= 0 AND fulfilled_quantity <= planned_quantity",
    )
    op.create_foreign_key(
        "fk_supply_line_allocations_fulfilled_by_user_id_users",
        "supply_line_allocations", "users", ["fulfilled_by_user_id"], ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "supply_department_debts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("outstanding_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("original_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="ACTIVE", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("first_request_id", sa.Uuid(), nullable=False),
        sa.Column("latest_request_id", sa.Uuid(), nullable=False),
        sa.Column("first_request_line_id", sa.Uuid(), nullable=False),
        sa.Column("latest_request_line_id", sa.Uuid(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("close_comment", sa.Text(), nullable=True),
        sa.Column("cancel_comment", sa.Text(), nullable=True),
        sa.Column("cycle_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_cycle_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'CLOSED', 'CANCELLED')",
            name="ck_supply_department_debts_status",
        ),
        sa.CheckConstraint(
            "outstanding_quantity >= 0 AND original_quantity > 0",
            name="ck_supply_department_debts_quantities",
        ),
        sa.CheckConstraint(
            "version >= 1 AND cycle_count >= 0",
            name="ck_supply_department_debts_version_cycles",
        ),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["supply_products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["supply_units.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_request_id"], ["supply_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["latest_request_id"], ["supply_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_request_line_id"], ["supply_request_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["latest_request_line_id"], ["supply_request_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cancelled_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_cycle_id"], ["supply_request_cycles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_supply_department_debts_active",
        "supply_department_debts",
        ["tenant_id", "department_id", "product_id", "unit_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_supply_department_debts_tenant_status_updated",
        "supply_department_debts", ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "supply_department_debt_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("debt_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(18, 3), nullable=False),
        sa.Column("quantity_before", sa.Numeric(18, 3), nullable=False),
        sa.Column("quantity_after", sa.Numeric(18, 3), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("request_line_id", sa.Uuid(), nullable=True),
        sa.Column("cycle_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('CREATED', 'INCREASED', 'INCLUDED_IN_REQUEST', "
            "'PARTIALLY_CLOSED', 'CLOSED', 'CANCELLED', 'REOPENED', 'ADJUSTED')",
            name="ck_supply_department_debt_events_type",
        ),
        sa.ForeignKeyConstraint(["debt_id"], ["supply_department_debts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["supply_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["request_line_id"], ["supply_request_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cycle_id"], ["supply_request_cycles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supply_department_debt_events_debt_created",
        "supply_department_debt_events", ["debt_id", "created_at"],
    )

    op.create_table(
        "supply_request_line_debt_links",
        sa.Column("request_line_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("debt_id", sa.Uuid(), nullable=True),
        sa.Column("contributed_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("included_debt_id", sa.Uuid(), nullable=True),
        sa.Column("included_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("applied_included_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("inclusion_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "contributed_quantity >= 0 AND included_quantity >= 0 AND "
            "applied_included_quantity >= 0 AND "
            "applied_included_quantity <= included_quantity",
            name="ck_supply_request_line_debt_links_quantities",
        ),
        sa.ForeignKeyConstraint(["request_line_id"], ["supply_request_lines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["debt_id"], ["supply_department_debts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["included_debt_id"], ["supply_department_debts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("request_line_id"),
    )
    op.create_index(
        "ix_supply_request_line_debt_links_tenant_debt",
        "supply_request_line_debt_links", ["tenant_id", "debt_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_request_line_debt_links_tenant_debt",
        table_name="supply_request_line_debt_links",
    )
    op.drop_table("supply_request_line_debt_links")
    op.drop_index(
        "ix_supply_department_debt_events_debt_created",
        table_name="supply_department_debt_events",
    )
    op.drop_table("supply_department_debt_events")
    op.drop_index(
        "ix_supply_department_debts_tenant_status_updated",
        table_name="supply_department_debts",
    )
    op.drop_index(
        "uq_supply_department_debts_active",
        table_name="supply_department_debts",
    )
    op.drop_table("supply_department_debts")
    op.drop_constraint(
        "fk_supply_line_allocations_fulfilled_by_user_id_users",
        "supply_line_allocations", type_="foreignkey",
    )
    op.drop_constraint(
        "ck_supply_line_allocations_fulfilled_quantity",
        "supply_line_allocations", type_="check",
    )
    op.drop_column("supply_line_allocations", "fulfillment_comment")
    op.drop_column("supply_line_allocations", "fulfilled_by_user_id")
    op.drop_column("supply_line_allocations", "fulfilled_at")
    op.drop_column("supply_line_allocations", "fulfilled_quantity")
    op.drop_constraint(
        "fk_supply_requests_fulfilled_by_user_id_users",
        "supply_requests", type_="foreignkey",
    )
    op.drop_column("supply_requests", "fulfilled_by_user_id")
    op.drop_column("supply_requests", "fulfilled_at")
