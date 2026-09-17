"""add supplier acceptances

Revision ID: 20260917_0049
Revises: 20260917_0048
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260917_0049"
down_revision: str | None = "20260917_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_supply_supplier_document_lines_tenant_id_order",
        "supply_supplier_document_lines", ["tenant_id", "id", "supplier_order_id"],
    )
    op.create_table(
        "supply_supplier_acceptances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_document_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_confirmation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), server_default="DRAFT", nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_acceptances_tenant_id"),
        sa.UniqueConstraint("tenant_id", "id", "supplier_order_id", name="uq_supply_supplier_acceptances_tenant_id_order"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_order_id"], ["supply_supplier_orders.tenant_id", "supply_supplier_orders.id"], name="fk_supply_supplier_acceptances_order_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_document_id", "supplier_order_id"], ["supply_supplier_documents.tenant_id", "supply_supplier_documents.id", "supply_supplier_documents.supplier_order_id"], name="fk_supply_supplier_acceptances_document_order_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_confirmation_id", "supplier_order_id"], ["supply_supplier_confirmations.tenant_id", "supply_supplier_confirmations.id", "supply_supplier_confirmations.supplier_order_id"], name="fk_supply_supplier_acceptances_confirmation_order_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('DRAFT', 'RECORDED', 'CANCELLED')", name="ck_supply_supplier_acceptances_status"),
        sa.CheckConstraint("(status = 'RECORDED' AND recorded_by_user_id IS NOT NULL AND recorded_at IS NOT NULL) OR (status <> 'RECORDED' AND recorded_by_user_id IS NULL AND recorded_at IS NULL)", name="ck_supply_supplier_acceptances_recorded"),
    )
    op.create_index("ix_supply_supplier_acceptances_order", "supply_supplier_acceptances", ["tenant_id", "supplier_order_id", "created_at"])
    op.create_index("ix_supply_supplier_acceptances_document", "supply_supplier_acceptances", ["tenant_id", "supplier_document_id", "status"])

    op.create_table(
        "supply_supplier_acceptance_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("acceptance_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_confirmation_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_document_line_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_order_line_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_confirmation_line_id", sa.Uuid(), nullable=True),
        sa.Column("product_name_snapshot", sa.String(240), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("unit_name_snapshot", sa.String(32), nullable=True),
        sa.Column("documented_quantity", sa.Numeric(30, 6), nullable=True),
        sa.Column("received_quantity", sa.Numeric(30, 6), nullable=False),
        sa.Column("accepted_quantity", sa.Numeric(30, 6), nullable=False),
        sa.Column("rejected_quantity", sa.Numeric(30, 6), nullable=False),
        sa.Column("documented_unit_price", sa.Numeric(30, 6), nullable=True),
        sa.Column("accepted_unit_price", sa.Numeric(30, 6), nullable=True),
        sa.Column("accepted_amount", sa.Numeric(30, 6), nullable=True),
        sa.Column("currency", sa.String(3), server_default="RUB", nullable=False),
        sa.Column("rejection_reason", sa.String(32), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_acceptance_lines_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id", "acceptance_id", "supplier_order_id"], ["supply_supplier_acceptances.tenant_id", "supply_supplier_acceptances.id", "supply_supplier_acceptances.supplier_order_id"], name="fk_supply_supplier_acceptance_lines_acceptance_order_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_document_line_id", "supplier_order_id"], ["supply_supplier_document_lines.tenant_id", "supply_supplier_document_lines.id", "supply_supplier_document_lines.supplier_order_id"], name="fk_supply_supplier_acceptance_lines_document_line_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_order_line_id", "supplier_order_id"], ["supply_supplier_order_lines.tenant_id", "supply_supplier_order_lines.id", "supply_supplier_order_lines.supplier_order_id"], name="fk_supply_supplier_acceptance_lines_order_line_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_confirmation_line_id", "supplier_order_line_id", "supplier_confirmation_id"], ["supply_supplier_confirmation_lines.tenant_id", "supply_supplier_confirmation_lines.id", "supply_supplier_confirmation_lines.supplier_order_line_id", "supply_supplier_confirmation_lines.confirmation_id"], name="fk_supply_supplier_acceptance_lines_confirmation_line_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["supply_products.tenant_id", "supply_products.id"], name="fk_supply_supplier_acceptance_lines_product_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "unit_id"], ["supply_units.tenant_id", "supply_units.id"], name="fk_supply_supplier_acceptance_lines_unit_tenant", ondelete="RESTRICT"),
        sa.CheckConstraint("received_quantity > 0", name="ck_supply_supplier_acceptance_lines_received"),
        sa.CheckConstraint("accepted_quantity >= 0", name="ck_supply_supplier_acceptance_lines_accepted"),
        sa.CheckConstraint("rejected_quantity >= 0", name="ck_supply_supplier_acceptance_lines_rejected"),
        sa.CheckConstraint("accepted_quantity + rejected_quantity = received_quantity", name="ck_supply_supplier_acceptance_lines_equation"),
        sa.CheckConstraint("documented_quantity IS NULL OR documented_quantity >= 0", name="ck_supply_supplier_acceptance_lines_documented"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_supplier_acceptance_lines_currency"),
        sa.CheckConstraint("(rejected_quantity = 0 AND rejection_reason IS NULL) OR (rejected_quantity > 0 AND rejection_reason IN ('DAMAGED','QUALITY_MISMATCH','WRONG_PRODUCT','WRONG_PACKAGE','EXPIRED','OTHER'))", name="ck_supply_supplier_acceptance_lines_rejection"),
        sa.CheckConstraint("rejection_reason <> 'OTHER' OR (comment IS NOT NULL AND length(trim(comment)) > 0)", name="ck_supply_supplier_acceptance_lines_other_comment"),
        sa.CheckConstraint("(supplier_confirmation_line_id IS NULL AND supplier_confirmation_id IS NULL) OR (supplier_confirmation_line_id IS NOT NULL AND supplier_confirmation_id IS NOT NULL AND supplier_order_line_id IS NOT NULL)", name="ck_supply_supplier_acceptance_lines_confirmation_link"),
    )
    op.create_index("ix_supply_supplier_acceptance_lines_acceptance", "supply_supplier_acceptance_lines", ["tenant_id", "acceptance_id", "created_at"])
    op.create_index("ix_supply_supplier_acceptance_lines_document_line", "supply_supplier_acceptance_lines", ["tenant_id", "supplier_document_line_id"])
    op.create_index("uq_supply_supplier_acceptance_lines_document_identity", "supply_supplier_acceptance_lines", ["tenant_id", "acceptance_id", "supplier_document_line_id"], unique=True, postgresql_where=sa.text("supplier_document_line_id IS NOT NULL"))
    op.create_index("uq_supply_supplier_acceptance_lines_order_identity", "supply_supplier_acceptance_lines", ["tenant_id", "acceptance_id", "supplier_order_line_id"], unique=True, postgresql_where=sa.text("supplier_document_line_id IS NULL AND supplier_order_line_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("supply_supplier_acceptance_lines")
    op.drop_table("supply_supplier_acceptances")
    op.drop_constraint(
        "uq_supply_supplier_document_lines_tenant_id_order",
        "supply_supplier_document_lines", type_="unique",
    )
