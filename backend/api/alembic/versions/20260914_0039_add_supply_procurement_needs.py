"""add supply procurement needs

Revision ID: 20260914_0039
Revises: 20260914_0038
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_0039"
down_revision: Union[str, Sequence[str], None] = "20260914_0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "supply_requests",
        sa.Column("need_date", sa.Date(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_supply_stock_calculation_lines_tenant_id",
        "supply_stock_calculation_lines",
        ["tenant_id", "id"],
    )
    op.create_unique_constraint(
        "uq_supply_department_debts_tenant_id",
        "supply_department_debts",
        ["tenant_id", "id"],
    )
    op.create_table(
        "supply_procurement_needs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("supply_request_line_id", sa.Uuid(), nullable=True),
        sa.Column("department_debt_id", sa.Uuid(), nullable=True),
        sa.Column("basis_stock_calculation_line_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("need_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="OPEN", nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reserved_purchase_request_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('REQUEST_LINE', 'DEPARTMENT_DEBT')",
            name="ck_supply_procurement_needs_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_PURCHASE_REQUEST', 'CLOSED', 'CANCELLED')",
            name="ck_supply_procurement_needs_status",
        ),
        sa.CheckConstraint(
            "reason IN ('INTERNAL_STOCK_DEFICIT', 'DEBT_CARRY_FORWARD', "
            "'ACTUAL_SHORTFALL')",
            name="ck_supply_procurement_needs_reason",
        ),
        sa.CheckConstraint(
            "(source_type = 'REQUEST_LINE' "
            "AND supply_request_line_id IS NOT NULL "
            "AND department_debt_id IS NULL "
            "AND basis_stock_calculation_line_id IS NOT NULL "
            "AND reason = 'INTERNAL_STOCK_DEFICIT') OR "
            "(source_type = 'DEPARTMENT_DEBT' "
            "AND department_debt_id IS NOT NULL "
            "AND supply_request_line_id IS NULL "
            "AND basis_stock_calculation_line_id IS NULL "
            "AND reason = 'DEBT_CARRY_FORWARD')",
            name="ck_supply_procurement_needs_source",
        ),
        sa.CheckConstraint(
            "quantity > 0", name="ck_supply_procurement_needs_quantity"
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_supply_procurement_needs_version"
        ),
        sa.CheckConstraint(
            "(status IN ('CLOSED', 'CANCELLED') AND closed_at IS NOT NULL) OR "
            "(status IN ('OPEN', 'IN_PURCHASE_REQUEST') AND closed_at IS NULL)",
            name="ck_supply_procurement_needs_closed_state",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supply_request_line_id"],
            ["supply_request_lines.tenant_id", "supply_request_lines.id"],
            name="fk_supply_procurement_needs_request_line_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_debt_id"],
            ["supply_department_debts.tenant_id", "supply_department_debts.id"],
            name="fk_supply_procurement_needs_debt_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "basis_stock_calculation_line_id"],
            [
                "supply_stock_calculation_lines.tenant_id",
                "supply_stock_calculation_lines.id",
            ],
            name="fk_supply_procurement_needs_basis_line_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["supply_products.tenant_id", "supply_products.id"],
            name="fk_supply_procurement_needs_product_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["supply_units.tenant_id", "supply_units.id"],
            name="fk_supply_procurement_needs_unit_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reserved_purchase_request_id"],
            ["supply_purchase_requests.tenant_id", "supply_purchase_requests.id"],
            name="fk_supply_procurement_needs_reserved_request_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_supply_procurement_needs_tenant_id"
        ),
    )
    op.create_index(
        "uq_supply_procurement_needs_open_request_line",
        "supply_procurement_needs",
        ["tenant_id", "supply_request_line_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'OPEN' AND source_type = 'REQUEST_LINE'"
        ),
        sqlite_where=sa.text(
            "status = 'OPEN' AND source_type = 'REQUEST_LINE'"
        ),
    )
    op.create_index(
        "uq_supply_procurement_needs_open_debt",
        "supply_procurement_needs",
        ["tenant_id", "department_debt_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'OPEN' AND source_type = 'DEPARTMENT_DEBT'"
        ),
        sqlite_where=sa.text(
            "status = 'OPEN' AND source_type = 'DEPARTMENT_DEBT'"
        ),
    )
    op.create_index(
        "ix_supply_procurement_needs_tenant_status_date_product_unit",
        "supply_procurement_needs",
        ["tenant_id", "status", "need_date", "product_id", "unit_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_procurement_needs_tenant_status_date_product_unit",
        table_name="supply_procurement_needs",
    )
    op.drop_index(
        "uq_supply_procurement_needs_open_debt",
        table_name="supply_procurement_needs",
    )
    op.drop_index(
        "uq_supply_procurement_needs_open_request_line",
        table_name="supply_procurement_needs",
    )
    op.drop_table("supply_procurement_needs")
    op.drop_constraint(
        "uq_supply_department_debts_tenant_id",
        "supply_department_debts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_supply_stock_calculation_lines_tenant_id",
        "supply_stock_calculation_lines",
        type_="unique",
    )
    op.drop_column("supply_requests", "need_date")
