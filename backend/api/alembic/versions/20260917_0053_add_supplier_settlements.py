"""add supplier settlements

Revision ID: 20260917_0053
Revises: 20260917_0052
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0053"
down_revision: str | None = "20260917_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _preflight(connection) -> None:
    ambiguous = connection.execute(sa.text("""
        SELECT d.tenant_id, d.supplier_order_id, s.display_name AS supplier,
               string_agg(
                   d.id::text || ':' || d.document_type || ':' || coalesce(d.document_number, '-')
                   || '|date=' || coalesce(d.document_date::text, '-')
                   || '|total=' || d.total_amount::text
                   || '|payments=' || coalesce((
                       SELECT string_agg(p.id::text, '|')
                       FROM supply_supplier_payments p
                       WHERE p.tenant_id = d.tenant_id
                         AND p.supplier_document_id = d.id
                         AND p.status = 'RECORDED'
                   ), '-'),
                   ', ' ORDER BY d.created_at
               ) AS documents
        FROM supply_supplier_documents d
        JOIN supply_suppliers s ON s.tenant_id = d.tenant_id AND s.id = d.supplier_id
        WHERE d.status = 'RECORDED' AND d.document_type IN ('INVOICE', 'UPD')
        GROUP BY d.tenant_id, d.supplier_order_id, s.display_name
        HAVING count(*) > 1
        ORDER BY d.tenant_id, d.supplier_order_id
    """)).mappings().all()
    if ambiguous:
        details = "; ".join(
            f"tenant={row['tenant_id']} order={row['supplier_order_id']} supplier={row['supplier']} documents={row['documents']}"
            for row in ambiguous
        )
        raise RuntimeError(f"Ambiguous legacy payable supplier documents: {details}")

    invalid_payments = connection.execute(sa.text("""
        SELECT p.id AS payment_id, p.tenant_id, p.supplier_document_id,
               d.supplier_order_id, d.document_type, d.document_number, d.document_date, d.total_amount
        FROM supply_supplier_payments p
        JOIN supply_supplier_documents d
          ON d.tenant_id = p.tenant_id AND d.id = p.supplier_document_id
        WHERE p.status = 'RECORDED'
          AND (d.status <> 'RECORDED' OR d.document_type NOT IN ('INVOICE', 'UPD'))
        ORDER BY p.tenant_id, p.id
    """)).mappings().all()
    if invalid_payments:
        details = "; ".join(
            f"payment={row['payment_id']} document={row['supplier_document_id']} type={row['document_type']} number={row['document_number']}"
            for row in invalid_payments
        )
        raise RuntimeError(f"Recorded payments linked to non-payable legacy documents: {details}")


def upgrade() -> None:
    connection = op.get_bind()
    _preflight(connection)

    op.create_unique_constraint(
        "uq_supply_supplier_payments_tenant_id_supplier",
        "supply_supplier_payments", ["tenant_id", "id", "supplier_id"],
    )
    op.create_table(
        "supply_supplier_obligations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_obligations_tenant_id"),
        sa.UniqueConstraint("tenant_id", "id", "supplier_id", name="uq_supply_supplier_obligations_tenant_supplier"),
        sa.UniqueConstraint("tenant_id", "id", "supplier_id", "supplier_order_id", name="uq_supply_supplier_obligations_tenant_links"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["supply_suppliers.tenant_id", "supply_suppliers.id"], name="fk_supply_supplier_obligations_supplier_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_order_id", "supplier_id"], ["supply_supplier_orders.tenant_id", "supply_supplier_orders.id", "supply_supplier_orders.supplier_id"], name="fk_supply_supplier_obligations_order_supplier_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_supply_supplier_obligations_status"),
    )
    op.create_index("ix_supply_supplier_obligations_order", "supply_supplier_obligations", ["tenant_id", "supplier_order_id", "status"])

    op.add_column("supply_supplier_documents", sa.Column("obligation_id", sa.Uuid(), nullable=True))
    op.add_column("supply_supplier_documents", sa.Column("financial_role", sa.String(24), nullable=True))
    op.create_foreign_key(
        "fk_supply_supplier_documents_obligation_links", "supply_supplier_documents", "supply_supplier_obligations",
        ["tenant_id", "obligation_id", "supplier_id", "supplier_order_id"],
        ["tenant_id", "id", "supplier_id", "supplier_order_id"], ondelete="RESTRICT",
    )

    op.execute("""
        UPDATE supply_supplier_documents
        SET financial_role = CASE document_type
            WHEN 'DELIVERY_NOTE' THEN 'SUPPORTING'
            WHEN 'INVOICE' THEN 'PAYABLE'
            WHEN 'UPD' THEN 'PAYABLE'
        END
    """)
    op.execute("""
        INSERT INTO supply_supplier_obligations
            (id, tenant_id, supplier_id, supplier_order_id, status, created_by_user_id)
        SELECT gen_random_uuid(), d.tenant_id, d.supplier_id, d.supplier_order_id, 'ACTIVE', d.recorded_by_user_id
        FROM supply_supplier_documents d
        WHERE d.status = 'RECORDED' AND d.document_type IN ('INVOICE', 'UPD')
    """)
    op.execute("""
        UPDATE supply_supplier_documents d
        SET obligation_id = o.id
        FROM supply_supplier_obligations o
        WHERE d.status = 'RECORDED' AND d.document_type IN ('INVOICE', 'UPD')
          AND o.tenant_id = d.tenant_id AND o.supplier_id = d.supplier_id
          AND o.supplier_order_id = d.supplier_order_id
    """)
    op.alter_column("supply_supplier_documents", "financial_role", nullable=False)
    op.create_check_constraint("ck_supply_supplier_documents_financial_role", "supply_supplier_documents", "financial_role IN ('PAYABLE', 'SUPPORTING', 'NON_FINANCIAL')")
    op.create_check_constraint("ck_supply_supplier_documents_payable_obligation", "supply_supplier_documents", "status <> 'RECORDED' OR financial_role <> 'PAYABLE' OR obligation_id IS NOT NULL")
    op.create_index(
        "uq_supply_supplier_documents_active_payable_obligation", "supply_supplier_documents",
        ["tenant_id", "obligation_id"], unique=True,
        postgresql_where=sa.text("status = 'RECORDED' AND financial_role = 'PAYABLE'"),
    )

    op.create_table(
        "supply_supplier_payment_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_document_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(30, 6), nullable=False),
        sa.Column("status", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reversed_amount", sa.Numeric(30, 6), nullable=True),
        sa.Column("reversed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverse_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_payment_allocations_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id", "payment_id", "supplier_id"], ["supply_supplier_payments.tenant_id", "supply_supplier_payments.id", "supply_supplier_payments.supplier_id"], name="fk_supply_payment_allocations_payment_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_document_id", "supplier_id"], ["supply_supplier_documents.tenant_id", "supply_supplier_documents.id", "supply_supplier_documents.supplier_id"], name="fk_supply_payment_allocations_document_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "obligation_id", "supplier_id"], ["supply_supplier_obligations.tenant_id", "supply_supplier_obligations.id", "supply_supplier_obligations.supplier_id"], name="fk_supply_payment_allocations_obligation_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reversed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("amount > 0", name="ck_supply_payment_allocations_amount"),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVERSED')", name="ck_supply_payment_allocations_status"),
        sa.CheckConstraint("(status = 'ACTIVE' AND reversed_amount IS NULL AND reversed_by_user_id IS NULL AND reversed_at IS NULL AND reverse_reason IS NULL) OR (status = 'REVERSED' AND reversed_amount > 0 AND reversed_amount <= amount AND reversed_by_user_id IS NOT NULL AND reversed_at IS NOT NULL AND reverse_reason IS NOT NULL)", name="ck_supply_payment_allocations_reversal"),
    )
    op.create_index("ix_supply_payment_allocations_payment", "supply_supplier_payment_allocations", ["tenant_id", "payment_id", "status"])
    op.create_index("ix_supply_payment_allocations_document", "supply_supplier_payment_allocations", ["tenant_id", "supplier_document_id", "status"])
    op.create_index("uq_supply_payment_allocations_active_pair", "supply_supplier_payment_allocations", ["tenant_id", "payment_id", "supplier_document_id"], unique=True, postgresql_where=sa.text("status = 'ACTIVE'"))
    op.execute("""
        INSERT INTO supply_supplier_payment_allocations
            (id, tenant_id, supplier_id, payment_id, supplier_document_id, obligation_id, amount, status, created_by_user_id, created_at)
        SELECT gen_random_uuid(), p.tenant_id, p.supplier_id, p.id, p.supplier_document_id,
               d.obligation_id, p.amount, 'ACTIVE', p.recorded_by_user_id, p.recorded_at
        FROM supply_supplier_payments p
        JOIN supply_supplier_documents d ON d.tenant_id = p.tenant_id AND d.id = p.supplier_document_id
        WHERE p.status = 'RECORDED'
    """)

    op.create_table(
        "supply_supplier_settlement_adjustments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_payment_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column("direction", sa.String(24), nullable=True),
        sa.Column("amount", sa.Numeric(30, 6), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), server_default="RECORDED", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_settlement_adjustments_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["supply_suppliers.tenant_id", "supply_suppliers.id"], name="fk_supply_settlement_adjustments_supplier_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_payment_id", "supplier_id"], ["supply_supplier_payments.tenant_id", "supply_supplier_payments.id", "supply_supplier_payments.supplier_id"], name="fk_supply_settlement_adjustments_payment_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("type IN ('SUPPLIER_REFUND', 'MANUAL_CORRECTION')", name="ck_supply_settlement_adjustments_type"),
        sa.CheckConstraint("direction IS NULL OR direction IN ('INCREASE_DEBT', 'DECREASE_DEBT')", name="ck_supply_settlement_adjustments_direction"),
        sa.CheckConstraint("amount > 0", name="ck_supply_settlement_adjustments_amount"),
        sa.CheckConstraint("status = 'RECORDED'", name="ck_supply_settlement_adjustments_status"),
        sa.CheckConstraint("(type = 'SUPPLIER_REFUND' AND supplier_payment_id IS NOT NULL AND direction IS NULL) OR (type = 'MANUAL_CORRECTION' AND supplier_payment_id IS NULL AND direction IS NOT NULL AND comment IS NOT NULL AND btrim(comment) <> '')", name="ck_supply_settlement_adjustments_semantics"),
    )
    op.create_index("ix_supply_settlement_adjustments_supplier_date", "supply_supplier_settlement_adjustments", ["tenant_id", "supplier_id", "effective_date"])
    op.create_index("ix_supply_settlement_adjustments_payment", "supply_supplier_settlement_adjustments", ["tenant_id", "supplier_payment_id"])


def downgrade() -> None:
    op.drop_table("supply_supplier_settlement_adjustments")
    op.drop_table("supply_supplier_payment_allocations")
    op.drop_index("uq_supply_supplier_documents_active_payable_obligation", table_name="supply_supplier_documents")
    op.drop_constraint("ck_supply_supplier_documents_payable_obligation", "supply_supplier_documents", type_="check")
    op.drop_constraint("ck_supply_supplier_documents_financial_role", "supply_supplier_documents", type_="check")
    op.drop_constraint("fk_supply_supplier_documents_obligation_links", "supply_supplier_documents", type_="foreignkey")
    op.drop_column("supply_supplier_documents", "financial_role")
    op.drop_column("supply_supplier_documents", "obligation_id")
    op.drop_table("supply_supplier_obligations")
    op.drop_constraint("uq_supply_supplier_payments_tenant_id_supplier", "supply_supplier_payments", type_="unique")
