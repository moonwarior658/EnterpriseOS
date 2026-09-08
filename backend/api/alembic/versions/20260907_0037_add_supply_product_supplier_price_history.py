"""add supply product supplier price history

Revision ID: 20260907_0037
Revises: 20260907_0036
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260907_0037"
down_revision: Union[str, Sequence[str], None] = "20260907_0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_product_supplier_price_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("product_supplier_id", sa.Uuid(), nullable=False),
        sa.Column("price_per_package", sa.Numeric(18, 2), nullable=False),
        sa.Column("package_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("package_unit_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("base_unit_price_snapshot", sa.Numeric(30, 6), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "effective_from", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "price_per_package > 0",
            name="ck_supply_product_supplier_price_history_price",
        ),
        sa.CheckConstraint(
            "package_quantity > 0",
            name="ck_supply_product_supplier_price_history_quantity",
        ),
        sa.CheckConstraint(
            "base_unit_price_snapshot > 0",
            name="ck_supply_product_supplier_price_history_base_price",
        ),
        sa.CheckConstraint(
            "currency = 'RUB'",
            name="ck_supply_product_supplier_price_history_currency",
        ),
        sa.CheckConstraint(
            "source = 'MANUAL'",
            name="ck_supply_product_supplier_price_history_source",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"], ["users.id"],
            name="fk_supply_product_supplier_price_history_changed_by_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_supplier_id"],
            ["supply_product_suppliers.tenant_id", "supply_product_suppliers.id"],
            name="fk_supply_product_supplier_price_history_relation_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "package_unit_id"],
            ["supply_units.tenant_id", "supply_units.id"],
            name="fk_supply_product_supplier_price_history_unit_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supply_product_supplier_price_history_timeline",
        "supply_product_supplier_price_history",
        ["tenant_id", "product_supplier_id", "effective_from", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_product_supplier_price_history_timeline",
        table_name="supply_product_supplier_price_history",
    )
    op.drop_table("supply_product_supplier_price_history")
