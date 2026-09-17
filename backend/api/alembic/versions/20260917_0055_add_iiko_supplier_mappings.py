"""add iiko supplier mappings

Revision ID: 20260917_0055
Revises: 20260917_0054
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0055"
down_revision: str | None = "20260917_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "iiko_supplier_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_supplier_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_supplier_name", sa.String(240), nullable=False),
        sa.Column("iiko_supplier_code", sa.String(160), nullable=True),
        sa.Column("iiko_supplier_inn", sa.String(32), nullable=True),
        sa.Column("iiko_supplier_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(16), nullable=False, server_default="CONFIRMED"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_user_id", sa.Integer(), nullable=True),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_iiko_supplier_mappings_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["supply_suppliers.tenant_id", "supply_suppliers.id"],
            name="fk_iiko_supplier_mappings_supplier_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["archived_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["iiko_supplier_mappings.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('CONFIRMED', 'ARCHIVED')", name="iiko_supplier_mapping_status"),
        sa.CheckConstraint(
            "(status = 'CONFIRMED' AND archived_at IS NULL) OR "
            "(status = 'ARCHIVED' AND archived_at IS NOT NULL)",
            name="ck_iiko_supplier_mappings_archive_state",
        ),
    )
    op.create_index(
        "uq_iiko_supplier_mappings_active_supplier",
        "iiko_supplier_mappings", ["tenant_id", "supplier_id"],
        unique=True, postgresql_where=sa.text("status = 'CONFIRMED'"),
    )
    op.create_index(
        "uq_iiko_supplier_mappings_active_external",
        "iiko_supplier_mappings", ["tenant_id", "iiko_supplier_id"],
        unique=True, postgresql_where=sa.text("status = 'CONFIRMED'"),
    )
    op.create_index(
        "ix_iiko_supplier_mappings_history",
        "iiko_supplier_mappings", ["tenant_id", "supplier_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("iiko_supplier_mappings")
