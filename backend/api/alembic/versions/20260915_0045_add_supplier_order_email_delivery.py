"""add supplier order email delivery

Revision ID: 20260915_0045
Revises: 20260915_0044
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_0045"
down_revision: Union[str, Sequence[str], None] = "20260915_0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("supply_supplier_orders", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("ck_supply_supplier_orders_status", "supply_supplier_orders", type_="check")
    op.drop_constraint("ck_supply_supplier_orders_timestamps", "supply_supplier_orders", type_="check")
    op.create_check_constraint(
        "ck_supply_supplier_orders_status", "supply_supplier_orders",
        "status IN ('DRAFT', 'READY', 'SENT', 'CANCELLED')",
    )
    op.create_check_constraint(
        "ck_supply_supplier_orders_timestamps", "supply_supplier_orders",
        "(status = 'READY' AND confirmed_at IS NOT NULL AND cancelled_at IS NULL AND sent_at IS NULL) OR "
        "(status = 'SENT' AND confirmed_at IS NOT NULL AND cancelled_at IS NULL AND sent_at IS NOT NULL) OR "
        "(status = 'CANCELLED' AND confirmed_at IS NULL AND cancelled_at IS NOT NULL AND sent_at IS NULL) OR "
        "(status = 'DRAFT' AND confirmed_at IS NULL AND cancelled_at IS NULL AND sent_at IS NULL)",
    )
    op.create_table(
        "supply_supplier_order_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("supplier_order_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("automation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_number > 0", name="ck_supply_supplier_order_delivery_attempts_number"),
        sa.CheckConstraint("status IN ('PENDING', 'DISPATCHED', 'SUCCEEDED', 'FAILED')", name="ck_supply_supplier_order_delivery_attempts_status"),
        sa.CheckConstraint(
            "(status = 'PENDING' AND dispatched_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'DISPATCHED' AND dispatched_at IS NOT NULL AND completed_at IS NULL) OR "
            "(status = 'SUCCEEDED' AND dispatched_at IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(status = 'FAILED' AND completed_at IS NOT NULL)",
            name="ck_supply_supplier_order_delivery_attempts_timestamps",
        ),
        sa.ForeignKeyConstraint(["automation_execution_id"], ["automation_executions.execution_id"], name="fk_supply_supplier_order_delivery_attempts_execution", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_supply_supplier_order_delivery_attempts_created_by", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_order_id"], ["supply_supplier_orders.tenant_id", "supply_supplier_orders.id"], name="fk_supply_supplier_order_delivery_attempts_order_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_order_delivery_attempts_tenant_id"),
        sa.UniqueConstraint("tenant_id", "supplier_order_id", "attempt_number", name="uq_supply_supplier_order_delivery_attempts_number"),
        sa.UniqueConstraint("automation_execution_id", name="uq_supply_supplier_order_delivery_attempts_execution"),
        sa.UniqueConstraint("idempotency_key", name="uq_supply_supplier_order_delivery_attempts_idempotency"),
    )
    op.create_index(
        "uq_supply_supplier_order_delivery_attempts_active",
        "supply_supplier_order_delivery_attempts", ["tenant_id", "supplier_order_id"],
        unique=True, postgresql_where=sa.text("status IN ('PENDING', 'DISPATCHED', 'SUCCEEDED')"),
        sqlite_where=sa.text("status IN ('PENDING', 'DISPATCHED', 'SUCCEEDED')"),
    )
    op.create_index(
        "ix_supply_supplier_order_delivery_attempts_history",
        "supply_supplier_order_delivery_attempts", ["tenant_id", "supplier_order_id", "attempt_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_supply_supplier_order_delivery_attempts_history", table_name="supply_supplier_order_delivery_attempts")
    op.drop_index("uq_supply_supplier_order_delivery_attempts_active", table_name="supply_supplier_order_delivery_attempts")
    op.drop_table("supply_supplier_order_delivery_attempts")
    op.drop_constraint("ck_supply_supplier_orders_timestamps", "supply_supplier_orders", type_="check")
    op.drop_constraint("ck_supply_supplier_orders_status", "supply_supplier_orders", type_="check")
    op.execute("UPDATE supply_supplier_orders SET status = 'READY', sent_at = NULL WHERE status = 'SENT'")
    op.create_check_constraint("ck_supply_supplier_orders_status", "supply_supplier_orders", "status IN ('DRAFT', 'READY', 'CANCELLED')")
    op.create_check_constraint(
        "ck_supply_supplier_orders_timestamps", "supply_supplier_orders",
        "(status = 'READY' AND confirmed_at IS NOT NULL AND cancelled_at IS NULL) OR "
        "(status = 'CANCELLED' AND confirmed_at IS NULL AND cancelled_at IS NOT NULL) OR "
        "(status = 'DRAFT' AND confirmed_at IS NULL AND cancelled_at IS NULL)",
    )
    op.drop_column("supply_supplier_orders", "sent_at")
