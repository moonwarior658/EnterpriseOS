"""add supply supplier orders

Revision ID: 20260915_0043
Revises: 20260914_0042
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_0043"
down_revision: Union[str, Sequence[str], None] = "20260914_0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_supplier_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_request_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("planned_delivery_date", sa.Date(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("total_amount", sa.Numeric(30, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('DRAFT', 'READY', 'CANCELLED')", name="ck_supply_supplier_orders_status"),
        sa.CheckConstraint("total_amount > 0", name="ck_supply_supplier_orders_total"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_supplier_orders_currency"),
        sa.CheckConstraint(
            "(status = 'READY' AND confirmed_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'CANCELLED' AND confirmed_at IS NULL AND cancelled_at IS NOT NULL) OR "
            "(status = 'DRAFT' AND confirmed_at IS NULL AND cancelled_at IS NULL)",
            name="ck_supply_supplier_orders_timestamps",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_supply_supplier_orders_created_by_user_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["supply_suppliers.tenant_id", "supply_suppliers.id"], name="fk_supply_supplier_orders_supplier_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "purchase_request_id"], ["supply_purchase_requests.tenant_id", "supply_purchase_requests.id"], name="fk_supply_supplier_orders_request_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_orders_tenant_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_supply_supplier_orders_tenant_number"),
    )
    op.create_index("ix_supply_supplier_orders_list", "supply_supplier_orders", ["tenant_id", "status", "updated_at"])
    op.create_index("ix_supply_supplier_orders_supplier", "supply_supplier_orders", ["tenant_id", "supplier_id"])
    op.create_index("ix_supply_supplier_orders_request", "supply_supplier_orders", ["tenant_id", "purchase_request_id"])

    op.create_table(
        "supply_supplier_order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=False),
        sa.Column("source_allocation_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_name_snapshot", sa.String(length=240), nullable=False),
        sa.Column("packages_count", sa.Integer(), nullable=False),
        sa.Column("package_quantity_snapshot", sa.Numeric(18, 3), nullable=False),
        sa.Column("package_unit_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("quantity_base", sa.Numeric(30, 6), nullable=False),
        sa.Column("price_per_package_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("base_unit_price_snapshot", sa.Numeric(30, 6), nullable=False),
        sa.Column("planned_amount", sa.Numeric(30, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("is_active_owner", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("packages_count > 0", name="ck_supply_supplier_order_lines_packages"),
        sa.CheckConstraint("package_quantity_snapshot > 0", name="ck_supply_supplier_order_lines_package_quantity"),
        sa.CheckConstraint("quantity_base > 0", name="ck_supply_supplier_order_lines_quantity"),
        sa.CheckConstraint("price_per_package_snapshot > 0", name="ck_supply_supplier_order_lines_package_price"),
        sa.CheckConstraint("base_unit_price_snapshot > 0", name="ck_supply_supplier_order_lines_base_price"),
        sa.CheckConstraint("planned_amount > 0", name="ck_supply_supplier_order_lines_amount"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_supplier_order_lines_currency"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_order_id"], ["supply_supplier_orders.tenant_id", "supply_supplier_orders.id"], name="fk_supply_supplier_order_lines_order_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "source_allocation_id"], ["supply_purchase_allocations.tenant_id", "supply_purchase_allocations.id"], name="fk_supply_supplier_order_lines_allocation_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["supply_products.tenant_id", "supply_products.id"], name="fk_supply_supplier_order_lines_product_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "package_unit_id_snapshot"], ["supply_units.tenant_id", "supply_units.id"], name="fk_supply_supplier_order_lines_unit_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_order_lines_tenant_id"),
    )
    op.create_index("ix_supply_supplier_order_lines_order", "supply_supplier_order_lines", ["tenant_id", "supplier_order_id"])
    op.create_index(
        "uq_supply_supplier_order_lines_active_allocation",
        "supply_supplier_order_lines", ["tenant_id", "source_allocation_id"],
        unique=True, postgresql_where=sa.text("is_active_owner = true"),
        sqlite_where=sa.text("is_active_owner = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_supply_supplier_order_lines_active_allocation", table_name="supply_supplier_order_lines")
    op.drop_index("ix_supply_supplier_order_lines_order", table_name="supply_supplier_order_lines")
    op.drop_table("supply_supplier_order_lines")
    op.drop_index("ix_supply_supplier_orders_request", table_name="supply_supplier_orders")
    op.drop_index("ix_supply_supplier_orders_supplier", table_name="supply_supplier_orders")
    op.drop_index("ix_supply_supplier_orders_list", table_name="supply_supplier_orders")
    op.drop_table("supply_supplier_orders")
