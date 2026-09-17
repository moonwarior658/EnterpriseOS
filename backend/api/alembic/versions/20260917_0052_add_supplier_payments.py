"""add supplier payments foundation

Revision ID: 20260917_0052
Revises: 20260917_0051
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0052"
down_revision: str | None = "20260917_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_supply_supplier_orders_tenant_id_supplier",
        "supply_supplier_orders", ["tenant_id", "id", "supplier_id"],
    )
    op.create_unique_constraint(
        "uq_supply_supplier_documents_tenant_id_supplier",
        "supply_supplier_documents", ["tenant_id", "id", "supplier_id"],
    )
    op.add_column(
        "supply_supplier_documents",
        sa.Column("payment_due_date", sa.Date(), nullable=True),
    )
    op.create_table(
        "supply_supplier_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_document_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=True),
        sa.Column("payment_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="DRAFT", nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(30, 6), nullable=False),
        sa.Column("currency", sa.String(3), server_default="RUB", nullable=False),
        sa.Column("payment_order_number", sa.String(128), nullable=True),
        sa.Column("payment_order_date", sa.Date(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_payments_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["supply_suppliers.tenant_id", "supply_suppliers.id"],
            name="fk_supply_supplier_payments_supplier_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_document_id", "supplier_id"],
            [
                "supply_supplier_documents.tenant_id",
                "supply_supplier_documents.id",
                "supply_supplier_documents.supplier_id",
            ],
            name="fk_supply_supplier_payments_document_supplier_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_order_id", "supplier_id"],
            [
                "supply_supplier_orders.tenant_id",
                "supply_supplier_orders.id",
                "supply_supplier_orders.supplier_id",
            ],
            name="fk_supply_supplier_payments_order_supplier_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "payment_type IN ('PREPAYMENT','POSTPAYMENT')",
            name="ck_supply_supplier_payments_type",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','RECORDED','CANCELLED')",
            name="ck_supply_supplier_payments_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_supply_supplier_payments_amount"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_supply_supplier_payments_currency"),
        sa.CheckConstraint(
            "(payment_order_number IS NULL AND payment_order_date IS NULL) OR "
            "(payment_order_number IS NOT NULL AND payment_order_date IS NOT NULL)",
            name="ck_supply_supplier_payments_order_fields",
        ),
        sa.CheckConstraint(
            "payment_type = 'PREPAYMENT' OR supplier_document_id IS NOT NULL",
            name="ck_supply_supplier_payments_postpayment_document",
        ),
        sa.CheckConstraint(
            "supplier_document_id IS NULL OR supplier_order_id IS NOT NULL",
            name="ck_supply_supplier_payments_document_order",
        ),
        sa.CheckConstraint(
            "(status = 'RECORDED' AND recorded_by_user_id IS NOT NULL AND recorded_at IS NOT NULL) OR "
            "(status IN ('DRAFT','CANCELLED') AND recorded_by_user_id IS NULL AND recorded_at IS NULL)",
            name="ck_supply_supplier_payments_recorded",
        ),
    )
    op.create_index(
        "uq_supply_supplier_payments_order_identity",
        "supply_supplier_payments",
        ["tenant_id", "supplier_id", "payment_date", "amount", "payment_order_number"],
        unique=True,
        postgresql_where=sa.text("payment_order_number IS NOT NULL AND status <> 'CANCELLED'"),
        sqlite_where=sa.text("payment_order_number IS NOT NULL AND status <> 'CANCELLED'"),
    )
    op.create_index(
        "ix_supply_supplier_payments_list",
        "supply_supplier_payments", ["tenant_id", "payment_date", "status"],
    )
    op.create_index(
        "ix_supply_supplier_payments_document",
        "supply_supplier_payments", ["tenant_id", "supplier_document_id", "status"],
    )
    op.create_index(
        "ix_supply_supplier_payments_order",
        "supply_supplier_payments", ["tenant_id", "supplier_order_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("supply_supplier_payments")
    op.drop_column("supply_supplier_documents", "payment_due_date")
    op.drop_constraint(
        "uq_supply_supplier_documents_tenant_id_supplier",
        "supply_supplier_documents", type_="unique",
    )
    op.drop_constraint(
        "uq_supply_supplier_orders_tenant_id_supplier",
        "supply_supplier_orders", type_="unique",
    )
