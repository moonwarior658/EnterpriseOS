"""add supplier documents

Revision ID: 20260917_0048
Revises: 20260917_0047
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0048"
down_revision: Union[str, Sequence[str], None] = "20260917_0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_supply_supplier_order_lines_tenant_id_order",
        "supply_supplier_order_lines", ["tenant_id", "id", "supplier_order_id"],
    )
    op.create_unique_constraint(
        "uq_supply_supplier_confirmations_tenant_id_order",
        "supply_supplier_confirmations", ["tenant_id", "id", "supplier_order_id"],
    )
    op.create_unique_constraint(
        "uq_supply_supplier_confirmation_lines_tenant_links",
        "supply_supplier_confirmation_lines",
        ["tenant_id", "id", "supplier_order_line_id", "confirmation_id"],
    )

    op.create_table(
        "supply_supplier_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_confirmation_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=24), nullable=False),
        sa.Column("document_number", sa.String(length=128), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("supplier_display_name_snapshot", sa.String(length=240), nullable=False),
        sa.Column("supplier_inn_snapshot", sa.String(length=12), nullable=True),
        sa.Column("supplier_kpp_snapshot", sa.String(length=9), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("total_amount", sa.Numeric(30, 6), server_default="0", nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("document_type IN ('INVOICE', 'DELIVERY_NOTE', 'UPD')", name="ck_supply_supplier_documents_type"),
        sa.CheckConstraint("status IN ('DRAFT', 'RECORDED', 'CANCELLED')", name="ck_supply_supplier_documents_status"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_supplier_documents_currency"),
        sa.CheckConstraint("total_amount >= 0", name="ck_supply_supplier_documents_total_nonnegative"),
        sa.CheckConstraint(
            "(status = 'RECORDED' AND document_number IS NOT NULL AND document_date IS NOT NULL "
            "AND total_amount > 0 AND recorded_by_user_id IS NOT NULL AND recorded_at IS NOT NULL) OR "
            "(status <> 'RECORDED' AND recorded_by_user_id IS NULL AND recorded_at IS NULL)",
            name="ck_supply_supplier_documents_recorded",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_order_id"],
            ["supply_supplier_orders.tenant_id", "supply_supplier_orders.id"],
            name="fk_supply_supplier_documents_order_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_confirmation_id", "supplier_order_id"],
            ["supply_supplier_confirmations.tenant_id", "supply_supplier_confirmations.id", "supply_supplier_confirmations.supplier_order_id"],
            name="fk_supply_supplier_documents_confirmation_order_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["supply_suppliers.tenant_id", "supply_suppliers.id"],
            name="fk_supply_supplier_documents_supplier_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], name="fk_supply_supplier_documents_recorded_by", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_supply_supplier_documents_created_by", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_documents_tenant_id"),
        sa.UniqueConstraint("tenant_id", "id", "supplier_order_id", name="uq_supply_supplier_documents_tenant_id_order"),
        sa.UniqueConstraint("tenant_id", "id", "supplier_order_id", "supplier_confirmation_id", name="uq_supply_supplier_documents_tenant_id_order_confirmation"),
    )
    op.create_index(
        "uq_supply_supplier_documents_identity", "supply_supplier_documents",
        ["tenant_id", "supplier_id", "document_type", "document_number", "document_date"],
        unique=True,
        postgresql_where=sa.text("document_number IS NOT NULL AND document_date IS NOT NULL AND status <> 'CANCELLED'"),
        sqlite_where=sa.text("document_number IS NOT NULL AND document_date IS NOT NULL AND status <> 'CANCELLED'"),
    )
    op.create_index(
        "ix_supply_supplier_documents_order", "supply_supplier_documents",
        ["tenant_id", "supplier_order_id", "created_at"],
    )

    op.create_table(
        "supply_supplier_document_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("supplier_document_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_confirmation_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_order_line_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_confirmation_line_id", sa.Uuid(), nullable=True),
        sa.Column("product_name_snapshot", sa.String(length=240), nullable=False),
        sa.Column("pricing_basis", sa.String(length=24), nullable=False),
        sa.Column("package_quantity_snapshot", sa.Numeric(18, 3), nullable=True),
        sa.Column("package_unit_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column("unit_name_snapshot", sa.String(length=32), nullable=True),
        sa.Column("packages_count", sa.Integer(), nullable=True),
        sa.Column("quantity_base", sa.Numeric(30, 6), nullable=True),
        sa.Column("price_per_package", sa.Numeric(18, 2), nullable=True),
        sa.Column("unit_price", sa.Numeric(30, 6), nullable=True),
        sa.Column("line_amount", sa.Numeric(30, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("supplier_line_reference", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("pricing_basis IN ('PACKAGE', 'UNIT', 'FIXED_AMOUNT')", name="ck_supply_supplier_document_lines_pricing_basis"),
        sa.CheckConstraint("line_amount > 0", name="ck_supply_supplier_document_lines_amount"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_supplier_document_lines_currency"),
        sa.CheckConstraint(
            "(supplier_confirmation_line_id IS NULL AND supplier_confirmation_id IS NULL) OR "
            "(supplier_confirmation_line_id IS NOT NULL AND supplier_confirmation_id IS NOT NULL "
            "AND supplier_order_line_id IS NOT NULL)",
            name="ck_supply_supplier_document_lines_confirmation_link",
        ),
        sa.CheckConstraint(
            "(pricing_basis = 'PACKAGE' AND packages_count IS NOT NULL AND packages_count > 0 "
            "AND price_per_package IS NOT NULL AND price_per_package > 0 AND unit_price IS NULL "
            "AND ((package_quantity_snapshot IS NULL AND package_unit_id_snapshot IS NULL AND quantity_base IS NULL) "
            "OR (package_quantity_snapshot IS NOT NULL AND package_quantity_snapshot > 0 "
            "AND package_unit_id_snapshot IS NOT NULL AND quantity_base = packages_count * package_quantity_snapshot)) "
            "AND line_amount = packages_count * price_per_package) OR "
            "(pricing_basis = 'UNIT' AND packages_count IS NULL AND price_per_package IS NULL "
            "AND package_quantity_snapshot IS NULL AND quantity_base IS NOT NULL AND quantity_base > 0 "
            "AND package_unit_id_snapshot IS NOT NULL AND unit_price IS NOT NULL AND unit_price > 0 "
            "AND line_amount = ROUND(quantity_base * unit_price, 6)) OR "
            "(pricing_basis = 'FIXED_AMOUNT' AND packages_count IS NULL AND price_per_package IS NULL "
            "AND package_quantity_snapshot IS NULL AND package_unit_id_snapshot IS NULL "
            "AND quantity_base IS NULL AND unit_price IS NULL)",
            name="ck_supply_supplier_document_lines_pricing_fields",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_document_id", "supplier_order_id"],
            ["supply_supplier_documents.tenant_id", "supply_supplier_documents.id", "supply_supplier_documents.supplier_order_id"],
            name="fk_supply_supplier_document_lines_document_order_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_document_id", "supplier_order_id", "supplier_confirmation_id"],
            ["supply_supplier_documents.tenant_id", "supply_supplier_documents.id", "supply_supplier_documents.supplier_order_id", "supply_supplier_documents.supplier_confirmation_id"],
            name="fk_supply_supplier_document_lines_document_confirmation_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_order_line_id", "supplier_order_id"],
            ["supply_supplier_order_lines.tenant_id", "supply_supplier_order_lines.id", "supply_supplier_order_lines.supplier_order_id"],
            name="fk_supply_supplier_document_lines_order_line_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_confirmation_line_id", "supplier_order_line_id", "supplier_confirmation_id"],
            ["supply_supplier_confirmation_lines.tenant_id", "supply_supplier_confirmation_lines.id", "supply_supplier_confirmation_lines.supplier_order_line_id", "supply_supplier_confirmation_lines.confirmation_id"],
            name="fk_supply_supplier_document_lines_confirmation_line_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "package_unit_id_snapshot"],
            ["supply_units.tenant_id", "supply_units.id"],
            name="fk_supply_supplier_document_lines_unit_tenant", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_document_lines_tenant_id"),
    )
    op.create_index(
        "ix_supply_supplier_document_lines_document", "supply_supplier_document_lines",
        ["tenant_id", "supplier_document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_supply_supplier_document_lines_document", table_name="supply_supplier_document_lines")
    op.drop_table("supply_supplier_document_lines")
    op.drop_index("ix_supply_supplier_documents_order", table_name="supply_supplier_documents")
    op.drop_index("uq_supply_supplier_documents_identity", table_name="supply_supplier_documents")
    op.drop_table("supply_supplier_documents")
    op.drop_constraint("uq_supply_supplier_confirmation_lines_tenant_links", "supply_supplier_confirmation_lines", type_="unique")
    op.drop_constraint("uq_supply_supplier_confirmations_tenant_id_order", "supply_supplier_confirmations", type_="unique")
    op.drop_constraint("uq_supply_supplier_order_lines_tenant_id_order", "supply_supplier_order_lines", type_="unique")
