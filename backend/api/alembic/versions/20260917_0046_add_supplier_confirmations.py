"""add supplier confirmations

Revision ID: 20260917_0046
Revises: 20260915_0045
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0046"
down_revision: Union[str, Sequence[str], None] = "20260915_0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_supplier_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("response_type", sa.String(length=24), nullable=True),
        sa.Column("supplier_reference", sa.String(length=255), nullable=True),
        sa.Column("supplier_comment", sa.Text(), nullable=True),
        sa.Column("confirmed_delivery_date", sa.Date(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision_number > 0", name="ck_supply_supplier_confirmations_revision"),
        sa.CheckConstraint("status IN ('DRAFT', 'RECORDED', 'SUPERSEDED', 'CANCELLED')", name="ck_supply_supplier_confirmations_status"),
        sa.CheckConstraint("response_type IS NULL OR response_type IN ('CONFIRMED', 'PARTIALLY_CONFIRMED', 'REJECTED')", name="ck_supply_supplier_confirmations_response_type"),
        sa.CheckConstraint("(status = 'RECORDED' AND response_type IS NOT NULL AND recorded_at IS NOT NULL) OR (status <> 'RECORDED')", name="ck_supply_supplier_confirmations_recorded"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_order_id"], ["supply_supplier_orders.tenant_id", "supply_supplier_orders.id"], name="fk_supply_supplier_confirmations_order_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], name="fk_supply_supplier_confirmations_recorded_by", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_supply_supplier_confirmations_created_by", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_confirmations_tenant_id"),
        sa.UniqueConstraint("tenant_id", "supplier_order_id", "revision_number", name="uq_supply_supplier_confirmations_revision"),
    )
    op.create_index("uq_supply_supplier_confirmations_draft", "supply_supplier_confirmations", ["tenant_id", "supplier_order_id"], unique=True, postgresql_where=sa.text("status = 'DRAFT'"), sqlite_where=sa.text("status = 'DRAFT'"))
    op.create_index("uq_supply_supplier_confirmations_current", "supply_supplier_confirmations", ["tenant_id", "supplier_order_id"], unique=True, postgresql_where=sa.text("status = 'RECORDED'"), sqlite_where=sa.text("status = 'RECORDED'"))
    op.create_index("ix_supply_supplier_confirmations_history", "supply_supplier_confirmations", ["tenant_id", "supplier_order_id", "revision_number"])

    op.create_table(
        "supply_supplier_confirmation_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("confirmation_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_order_line_id", sa.Uuid(), nullable=False),
        sa.Column("response_status", sa.String(length=16), server_default="CONFIRMED", nullable=False),
        sa.Column("product_name_snapshot", sa.String(length=240), nullable=False),
        sa.Column("confirmed_packages_count", sa.Integer(), nullable=True),
        sa.Column("confirmed_package_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("confirmed_package_unit_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_quantity_base", sa.Numeric(30, 6), nullable=True),
        sa.Column("confirmed_price_per_package", sa.Numeric(18, 2), nullable=True),
        sa.Column("confirmed_planned_amount", sa.Numeric(30, 6), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("supplier_line_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("response_status IN ('CONFIRMED', 'CHANGED', 'REJECTED')", name="ck_supply_supplier_confirmation_lines_status"),
        sa.CheckConstraint("confirmed_packages_count IS NULL OR confirmed_packages_count > 0", name="ck_supply_supplier_confirmation_lines_packages"),
        sa.CheckConstraint("confirmed_package_quantity IS NULL OR confirmed_package_quantity > 0", name="ck_supply_supplier_confirmation_lines_package_quantity"),
        sa.CheckConstraint("confirmed_quantity_base IS NULL OR confirmed_quantity_base > 0", name="ck_supply_supplier_confirmation_lines_quantity"),
        sa.CheckConstraint("confirmed_price_per_package IS NULL OR confirmed_price_per_package > 0", name="ck_supply_supplier_confirmation_lines_price"),
        sa.CheckConstraint("confirmed_planned_amount IS NULL OR confirmed_planned_amount > 0", name="ck_supply_supplier_confirmation_lines_amount"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_supplier_confirmation_lines_currency"),
        sa.ForeignKeyConstraint(["tenant_id", "confirmation_id"], ["supply_supplier_confirmations.tenant_id", "supply_supplier_confirmations.id"], name="fk_supply_supplier_confirmation_lines_confirmation_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_order_line_id"], ["supply_supplier_order_lines.tenant_id", "supply_supplier_order_lines.id"], name="fk_supply_supplier_confirmation_lines_order_line_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "confirmed_package_unit_id"], ["supply_units.tenant_id", "supply_units.id"], name="fk_supply_supplier_confirmation_lines_unit_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_confirmation_lines_tenant_id"),
        sa.UniqueConstraint("tenant_id", "confirmation_id", "supplier_order_line_id", name="uq_supply_supplier_confirmation_lines_order_line"),
    )
    op.create_index("ix_supply_supplier_confirmation_lines_confirmation", "supply_supplier_confirmation_lines", ["tenant_id", "confirmation_id"])


def downgrade() -> None:
    op.drop_index("ix_supply_supplier_confirmation_lines_confirmation", table_name="supply_supplier_confirmation_lines")
    op.drop_table("supply_supplier_confirmation_lines")
    op.drop_index("ix_supply_supplier_confirmations_history", table_name="supply_supplier_confirmations")
    op.drop_index("uq_supply_supplier_confirmations_current", table_name="supply_supplier_confirmations")
    op.drop_index("uq_supply_supplier_confirmations_draft", table_name="supply_supplier_confirmations")
    op.drop_table("supply_supplier_confirmations")
