"""add supply purchase allocations

Revision ID: 20260914_0041
Revises: 20260914_0040
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_0041"
down_revision: Union[str, Sequence[str], None] = "20260914_0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_purchase_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("purchase_request_line_id", sa.Uuid(), nullable=False),
        sa.Column("product_supplier_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_base", sa.Numeric(30, 6), nullable=False),
        sa.Column("package_quantity_snapshot", sa.Numeric(18, 3), nullable=False),
        sa.Column("package_unit_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("packages_count", sa.Integer(), nullable=False),
        sa.Column("price_per_package_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("base_unit_price_snapshot", sa.Numeric(30, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("planned_amount", sa.Numeric(30, 6), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("packages_count > 0", name="ck_supply_purchase_allocations_packages"),
        sa.CheckConstraint("quantity_base > 0", name="ck_supply_purchase_allocations_quantity"),
        sa.CheckConstraint("package_quantity_snapshot > 0", name="ck_supply_purchase_allocations_package_quantity"),
        sa.CheckConstraint("price_per_package_snapshot > 0", name="ck_supply_purchase_allocations_package_price"),
        sa.CheckConstraint("base_unit_price_snapshot > 0", name="ck_supply_purchase_allocations_base_price"),
        sa.CheckConstraint("planned_amount > 0", name="ck_supply_purchase_allocations_amount"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_purchase_allocations_currency"),
        sa.CheckConstraint("status IN ('DRAFT', 'CONFIRMED')", name="ck_supply_purchase_allocations_status"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "purchase_request_line_id"],
            ["supply_purchase_request_lines.tenant_id", "supply_purchase_request_lines.id"],
            name="fk_supply_purchase_allocations_line_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_supplier_id"],
            ["supply_product_suppliers.tenant_id", "supply_product_suppliers.id"],
            name="fk_supply_purchase_allocations_relation_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "package_unit_id_snapshot"],
            ["supply_units.tenant_id", "supply_units.id"],
            name="fk_supply_purchase_allocations_unit_tenant", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_purchase_allocations_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "purchase_request_line_id", "product_supplier_id",
            name="uq_supply_purchase_allocations_line_relation",
        ),
    )
    op.create_index(
        "ix_supply_purchase_allocations_request_line", "supply_purchase_allocations",
        ["tenant_id", "purchase_request_line_id", "status"], unique=False,
    )
    op.create_index(
        "ix_supply_purchase_allocations_relation", "supply_purchase_allocations",
        ["tenant_id", "product_supplier_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_supply_purchase_allocations_relation", table_name="supply_purchase_allocations")
    op.drop_index("ix_supply_purchase_allocations_request_line", table_name="supply_purchase_allocations")
    op.drop_table("supply_purchase_allocations")
