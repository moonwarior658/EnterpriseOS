"""add persistent iiko incoming receipts

Revision ID: 20260917_0056
Revises: 20260917_0055
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0056"
down_revision: str | None = "20260917_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supply_iiko_incoming_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_acceptance_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("destination_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_supplier_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("eos_document_number", sa.String(64), nullable=False),
        sa.Column("date_incoming", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incoming_date", sa.Date(), nullable=False),
        sa.Column("iiko_document_id", sa.Uuid(), nullable=True),
        sa.Column("iiko_document_number", sa.String(128), nullable=True),
        sa.Column("iiko_status", sa.String(32), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("create_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("process_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("create_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_in_iiko_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("process_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_iiko_incoming_receipts_tenant_id"),
        sa.UniqueConstraint("tenant_id", "eos_document_number", name="uq_supply_iiko_incoming_receipts_document_number"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_acceptance_id"],
            ["supply_supplier_acceptances.tenant_id", "supply_supplier_acceptances.id"],
            name="fk_supply_iiko_incoming_receipts_acceptance_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["supply_suppliers.tenant_id", "supply_suppliers.id"],
            name="fk_supply_iiko_incoming_receipts_supplier_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "destination_mapping_id"],
            ["iiko_warehouse_mappings.tenant_id", "iiko_warehouse_mappings.id"],
            name="fk_supply_iiko_incoming_receipts_destination_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "iiko_supplier_mapping_id"],
            ["iiko_supplier_mappings.tenant_id", "iiko_supplier_mappings.id"],
            name="fk_supply_iiko_incoming_receipts_supplier_mapping_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('DRAFT','READY','CREATING','CREATED','PROCESSING','POSTED','FAILED','CANCELLED')",
            name="ck_supply_iiko_incoming_receipts_status",
        ),
        sa.CheckConstraint(
            "create_attempt_count >= 0 AND process_attempt_count >= 0",
            name="ck_supply_iiko_incoming_receipts_attempts",
        ),
    )
    op.create_index(
        "uq_supply_iiko_incoming_receipts_active_acceptance",
        "supply_iiko_incoming_receipts", ["tenant_id", "supplier_acceptance_id"],
        unique=True, postgresql_where=sa.text("status <> 'CANCELLED'"),
    )
    op.create_index(
        "uq_supply_iiko_incoming_receipts_iiko_document",
        "supply_iiko_incoming_receipts", ["tenant_id", "iiko_document_id"],
        unique=True, postgresql_where=sa.text("iiko_document_id IS NOT NULL"),
    )
    op.create_index(
        "ix_supply_iiko_incoming_receipts_status",
        "supply_iiko_incoming_receipts", ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "supply_iiko_incoming_receipt_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("acceptance_line_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_document_line_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_product_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_amount_unit_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_store_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 6), nullable=False),
        sa.Column("historical_unit_price", sa.Numeric(30, 9), nullable=False),
        sa.Column("allocated_sum", sa.Numeric(30, 6), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("accounted_quantity", sa.Numeric(30, 6), nullable=False, server_default="0"),
        sa.Column("accounted_sum", sa.Numeric(30, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_iiko_incoming_receipt_lines_tenant_id"),
        sa.UniqueConstraint("tenant_id", "receipt_id", "line_no", name="uq_supply_iiko_incoming_receipt_lines_number"),
        sa.UniqueConstraint("tenant_id", "receipt_id", "acceptance_line_id", name="uq_supply_iiko_incoming_receipt_lines_acceptance_line"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["supply_iiko_incoming_receipts.tenant_id", "supply_iiko_incoming_receipts.id"],
            name="fk_supply_iiko_incoming_receipt_lines_receipt_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "acceptance_line_id"],
            ["supply_supplier_acceptance_lines.tenant_id", "supply_supplier_acceptance_lines.id"],
            name="fk_supply_iiko_incoming_receipt_lines_acceptance_line_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_document_line_id"],
            ["supply_supplier_document_lines.tenant_id", "supply_supplier_document_lines.id"],
            name="fk_supply_iiko_incoming_receipt_lines_document_line_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["supply_products.tenant_id", "supply_products.id"],
            name="fk_supply_iiko_incoming_receipt_lines_product_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["supply_units.tenant_id", "supply_units.id"],
            name="fk_supply_iiko_incoming_receipt_lines_unit_tenant", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("line_no > 0", name="ck_supply_iiko_incoming_receipt_lines_number"),
        sa.CheckConstraint("quantity > 0", name="ck_supply_iiko_incoming_receipt_lines_quantity"),
        sa.CheckConstraint("historical_unit_price > 0", name="ck_supply_iiko_incoming_receipt_lines_price"),
        sa.CheckConstraint("allocated_sum >= 0", name="ck_supply_iiko_incoming_receipt_lines_sum"),
        sa.CheckConstraint(
            "accounted_quantity >= 0 AND accounted_quantity <= quantity",
            name="ck_supply_iiko_incoming_receipt_lines_accounted_quantity",
        ),
        sa.CheckConstraint(
            "accounted_sum >= 0 AND accounted_sum <= allocated_sum",
            name="ck_supply_iiko_incoming_receipt_lines_accounted_sum",
        ),
    )
    op.create_index(
        "ix_supply_iiko_incoming_receipt_lines_document_line",
        "supply_iiko_incoming_receipt_lines", ["tenant_id", "supplier_document_line_id"],
    )

    op.execute("""
        CREATE FUNCTION supply_iiko_receipt_line_snapshot_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE receipt_status text;
        DECLARE target_tenant_id text;
        DECLARE target_receipt_id uuid;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            target_tenant_id := OLD.tenant_id;
            target_receipt_id := OLD.receipt_id;
          ELSE
            target_tenant_id := NEW.tenant_id;
            target_receipt_id := NEW.receipt_id;
          END IF;
          SELECT status INTO receipt_status
          FROM supply_iiko_incoming_receipts
          WHERE tenant_id = target_tenant_id
            AND id = target_receipt_id;
          IF receipt_status <> 'DRAFT' THEN
            IF TG_OP = 'DELETE' OR TG_OP = 'INSERT' THEN
              RAISE EXCEPTION 'IIKO_RECEIPT_SNAPSHOT_IMMUTABLE';
            END IF;
            IF (NEW.acceptance_line_id, NEW.supplier_document_line_id, NEW.product_id,
                NEW.unit_id, NEW.iiko_product_id, NEW.iiko_amount_unit_id,
                NEW.iiko_store_id, NEW.quantity, NEW.historical_unit_price,
                NEW.allocated_sum, NEW.line_no)
               IS DISTINCT FROM
               (OLD.acceptance_line_id, OLD.supplier_document_line_id, OLD.product_id,
                OLD.unit_id, OLD.iiko_product_id, OLD.iiko_amount_unit_id,
                OLD.iiko_store_id, OLD.quantity, OLD.historical_unit_price,
                OLD.allocated_sum, OLD.line_no) THEN
              RAISE EXCEPTION 'IIKO_RECEIPT_SNAPSHOT_IMMUTABLE';
            END IF;
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_supply_iiko_receipt_line_snapshot_guard
        BEFORE INSERT OR UPDATE OR DELETE ON supply_iiko_incoming_receipt_lines
        FOR EACH ROW EXECUTE FUNCTION supply_iiko_receipt_line_snapshot_guard()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_supply_iiko_receipt_line_snapshot_guard ON supply_iiko_incoming_receipt_lines")
    op.execute("DROP FUNCTION IF EXISTS supply_iiko_receipt_line_snapshot_guard()")
    op.drop_table("supply_iiko_incoming_receipt_lines")
    op.drop_table("supply_iiko_incoming_receipts")
