"""add supply product suppliers

Revision ID: 20260907_0036
Revises: 20260907_0035
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260907_0036"
down_revision: Union[str, Sequence[str], None] = "20260907_0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_product_suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_product_name", sa.String(length=240), nullable=True),
        sa.Column("supplier_sku", sa.String(length=120), nullable=True),
        sa.Column("role", sa.String(length=16), server_default="BACKUP", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("package_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("package_unit_id", sa.Uuid(), nullable=False),
        sa.Column("price_per_package", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("unavailable_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('PRIMARY', 'BACKUP')", name="ck_supply_product_suppliers_role"),
        sa.CheckConstraint("priority >= 0", name="ck_supply_product_suppliers_priority"),
        sa.CheckConstraint("package_quantity > 0", name="ck_supply_product_suppliers_package_quantity"),
        sa.CheckConstraint("price_per_package IS NULL OR price_per_package > 0", name="ck_supply_product_suppliers_price"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_product_suppliers_currency"),
        sa.CheckConstraint("is_available = false OR unavailable_until IS NULL", name="ck_supply_product_suppliers_availability"),
        sa.CheckConstraint(
            "(is_active = true AND archived_at IS NULL AND archived_by_user_id IS NULL) OR "
            "(is_active = false AND archived_at IS NOT NULL AND archived_by_user_id IS NOT NULL)",
            name="ck_supply_product_suppliers_archive_state",
        ),
        sa.ForeignKeyConstraint(["archived_by_user_id"], ["users.id"], name="fk_supply_product_suppliers_archived_by_user_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["supply_products.tenant_id", "supply_products.id"], name="fk_supply_product_suppliers_product_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["supply_suppliers.tenant_id", "supply_suppliers.id"], name="fk_supply_product_suppliers_supplier_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "package_unit_id"], ["supply_units.tenant_id", "supply_units.id"], name="fk_supply_product_suppliers_package_unit_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_product_suppliers_tenant_id"),
    )
    op.create_index(
        "ix_supply_product_suppliers_product_order",
        "supply_product_suppliers",
        ["tenant_id", "product_id", "is_active", "priority"],
    )
    op.create_index(
        "uq_supply_product_suppliers_active_pair",
        "supply_product_suppliers",
        ["tenant_id", "product_id", "supplier_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
        sqlite_where=sa.text("is_active = true"),
    )
    op.create_index(
        "uq_supply_product_suppliers_active_primary",
        "supply_product_suppliers",
        ["tenant_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND role = 'PRIMARY'"),
        sqlite_where=sa.text("is_active = true AND role = 'PRIMARY'"),
    )


def downgrade() -> None:
    op.drop_index("uq_supply_product_suppliers_active_primary", table_name="supply_product_suppliers")
    op.drop_index("uq_supply_product_suppliers_active_pair", table_name="supply_product_suppliers")
    op.drop_index("ix_supply_product_suppliers_product_order", table_name="supply_product_suppliers")
    op.drop_table("supply_product_suppliers")
