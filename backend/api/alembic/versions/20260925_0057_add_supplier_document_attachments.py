"""add supplier document attachments

Revision ID: 20260925_0057
Revises: 20260917_0056
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260925_0057"
down_revision: str | None = "20260917_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supply_supplier_document_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_document_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id",
            name="uq_supply_supplier_document_attachments_tenant_id",
        ),
        sa.UniqueConstraint("stored_filename"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_document_id"],
            ["supply_supplier_documents.tenant_id", "supply_supplier_documents.id"],
            name="fk_supply_supplier_document_attachments_document_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name="ck_supply_supplier_document_attachments_size",
        ),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png')",
            name="ck_supply_supplier_document_attachments_content_type",
        ),
    )
    op.create_index(
        "ix_supply_supplier_document_attachments_document",
        "supply_supplier_document_attachments",
        ["tenant_id", "supplier_document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("supply_supplier_document_attachments")
