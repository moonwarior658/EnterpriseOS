"""add supply purchase requests

Revision ID: 20260914_0038
Revises: 20260907_0037
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_0038"
down_revision: Union[str, Sequence[str], None] = "20260907_0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_purchase_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("need_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'READY', 'CANCELLED')", name="ck_supply_purchase_requests_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_supply_purchase_requests_created_by_user_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_purchase_requests_tenant_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_supply_purchase_requests_tenant_number"),
    )
    op.create_index(
        "ix_supply_purchase_requests_tenant_need_date",
        "supply_purchase_requests", ["tenant_id", "need_date", "updated_at"],
    )
    op.create_table(
        "supply_purchase_request_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("purchase_request_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("manual_future_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_supply_purchase_request_lines_quantity"),
        sa.CheckConstraint("manual_future_quantity > 0", name="ck_supply_purchase_request_lines_manual_future_quantity"),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["supply_products.tenant_id", "supply_products.id"], name="fk_supply_purchase_request_lines_product_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "purchase_request_id"], ["supply_purchase_requests.tenant_id", "supply_purchase_requests.id"], name="fk_supply_purchase_request_lines_request_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "unit_id"], ["supply_units.tenant_id", "supply_units.id"], name="fk_supply_purchase_request_lines_unit_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_purchase_request_lines_tenant_id"),
        sa.UniqueConstraint("tenant_id", "purchase_request_id", "product_id", "unit_id", name="uq_supply_purchase_request_lines_product_unit"),
    )
    op.create_table(
        "supply_purchase_request_line_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("purchase_request_line_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_supply_purchase_request_line_sources_quantity"),
        sa.CheckConstraint("(source_type = 'MANUAL_FUTURE' AND source_id IS NULL) OR (source_type <> 'MANUAL_FUTURE' AND source_id IS NOT NULL)", name="ck_supply_purchase_request_line_sources_reference"),
        sa.CheckConstraint("source_type IN ('SUPPLY_REQUEST', 'DEPARTMENT_DEBT', 'MANUAL_FUTURE')", name="ck_supply_purchase_request_line_sources_type"),
        sa.ForeignKeyConstraint(["tenant_id", "purchase_request_line_id"], ["supply_purchase_request_lines.tenant_id", "supply_purchase_request_lines.id"], name="fk_supply_purchase_request_line_sources_line_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "unit_id"], ["supply_units.tenant_id", "supply_units.id"], name="fk_supply_purchase_request_line_sources_unit_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supply_purchase_request_line_sources_line",
        "supply_purchase_request_line_sources",
        ["tenant_id", "purchase_request_line_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_supply_purchase_request_line_sources_line", table_name="supply_purchase_request_line_sources")
    op.drop_table("supply_purchase_request_line_sources")
    op.drop_table("supply_purchase_request_lines")
    op.drop_index("ix_supply_purchase_requests_tenant_need_date", table_name="supply_purchase_requests")
    op.drop_table("supply_purchase_requests")
