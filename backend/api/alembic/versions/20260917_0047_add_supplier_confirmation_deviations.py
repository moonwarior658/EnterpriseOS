"""add supplier confirmation deviations

Revision ID: 20260917_0047
Revises: 20260917_0046
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0047"
down_revision: Union[str, Sequence[str], None] = "20260917_0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_supplier_confirmation_deviations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("confirmation_id", sa.Uuid(), nullable=False),
        sa.Column("confirmation_line_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_order_line_id", sa.Uuid(), nullable=True),
        sa.Column("deviation_type", sa.String(length=32), nullable=False),
        sa.Column("requires_decision", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="OPEN", nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=True),
        sa.Column("product_name_snapshot", sa.String(length=240), nullable=True),
        sa.Column("baseline_packages_count", sa.Integer(), nullable=True),
        sa.Column("confirmed_packages_count", sa.Integer(), nullable=True),
        sa.Column("baseline_package_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("confirmed_package_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("baseline_package_unit_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_package_unit_id", sa.Uuid(), nullable=True),
        sa.Column("package_unit_snapshot", sa.String(length=32), nullable=True),
        sa.Column("baseline_quantity", sa.Numeric(30, 6), nullable=True),
        sa.Column("confirmed_quantity", sa.Numeric(30, 6), nullable=True),
        sa.Column("quantity_delta", sa.Numeric(30, 6), nullable=True),
        sa.Column("baseline_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("confirmed_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("price_delta", sa.Numeric(18, 2), nullable=True),
        sa.Column("price_delta_percent", sa.Numeric(18, 6), nullable=True),
        sa.Column("baseline_amount", sa.Numeric(30, 6), nullable=True),
        sa.Column("confirmed_amount", sa.Numeric(30, 6), nullable=True),
        sa.Column("baseline_delivery_date", sa.Date(), nullable=True),
        sa.Column("confirmed_delivery_date", sa.Date(), nullable=True),
        sa.Column("delivery_delta_days", sa.Integer(), nullable=True),
        sa.Column("decision_type", sa.String(length=16), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "deviation_type IN ('LINE_REJECTED', 'QUANTITY_CHANGED', 'PRICE_CHANGED', 'DELIVERY_DATE_CHANGED')",
            name="ck_supply_confirmation_deviations_type",
        ),
        sa.CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_supply_confirmation_deviations_status"),
        sa.CheckConstraint("direction IS NULL OR direction IN ('INCREASED', 'DECREASED')", name="ck_supply_confirmation_deviations_direction"),
        sa.CheckConstraint("decision_type IS NULL OR decision_type IN ('ACCEPT', 'REJECT')", name="ck_supply_confirmation_deviations_decision_type"),
        sa.CheckConstraint(
            "(status = 'OPEN' AND decision_type IS NULL AND decision_comment IS NULL "
            "AND decided_by_user_id IS NULL AND decided_at IS NULL) OR "
            "(status = 'RESOLVED' AND requires_decision = true AND decision_type IS NOT NULL "
            "AND decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_supply_confirmation_deviations_decision_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "confirmation_id"],
            ["supply_supplier_confirmations.tenant_id", "supply_supplier_confirmations.id"],
            name="fk_supply_confirmation_deviations_confirmation_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "confirmation_line_id"],
            ["supply_supplier_confirmation_lines.tenant_id", "supply_supplier_confirmation_lines.id"],
            name="fk_supply_confirmation_deviations_line_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_order_line_id"],
            ["supply_supplier_order_lines.tenant_id", "supply_supplier_order_lines.id"],
            name="fk_supply_confirmation_deviations_order_line_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], name="fk_supply_confirmation_deviations_decided_by", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_confirmation_deviations_tenant_id"),
    )
    op.create_index(
        "uq_supply_confirmation_deviations_line_type",
        "supply_supplier_confirmation_deviations",
        ["tenant_id", "confirmation_id", "confirmation_line_id", "deviation_type"],
        unique=True,
        postgresql_where=sa.text("confirmation_line_id IS NOT NULL"),
        sqlite_where=sa.text("confirmation_line_id IS NOT NULL"),
    )
    op.create_index(
        "uq_supply_confirmation_deviations_header_type",
        "supply_supplier_confirmation_deviations",
        ["tenant_id", "confirmation_id", "deviation_type"],
        unique=True,
        postgresql_where=sa.text("confirmation_line_id IS NULL"),
        sqlite_where=sa.text("confirmation_line_id IS NULL"),
    )
    op.create_index(
        "ix_supply_confirmation_deviations_review",
        "supply_supplier_confirmation_deviations",
        ["tenant_id", "confirmation_id", "requires_decision", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_supply_confirmation_deviations_review", table_name="supply_supplier_confirmation_deviations")
    op.drop_index("uq_supply_confirmation_deviations_header_type", table_name="supply_supplier_confirmation_deviations")
    op.drop_index("uq_supply_confirmation_deviations_line_type", table_name="supply_supplier_confirmation_deviations")
    op.drop_table("supply_supplier_confirmation_deviations")
