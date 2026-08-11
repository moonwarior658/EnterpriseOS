"""add persistent iiko document write intents

Revision ID: 20260811_0030
Revises: 20260806_0029
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260811_0030"
down_revision: Union[str, Sequence[str], None] = "20260806_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "iiko_document_writes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supply_request_id", sa.Uuid(), nullable=False),
        sa.Column("source_store_id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_type",
            sa.Enum(
                "OUTGOING_INVOICE",
                name="iiko_document_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="OUTGOING_INVOICE",
            nullable=False,
        ),
        sa.Column("iiko_document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "iiko_document_number",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CREATED",
                "FAILED",
                "UNKNOWN",
                name="iiko_document_write_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=160), nullable=True),
        sa.CheckConstraint(
            "status != 'CREATED' OR iiko_document_number IS NOT NULL",
            name="ck_iiko_document_writes_created_number",
        ),
        sa.ForeignKeyConstraint(
            ["supply_request_id"],
            ["supply_requests.id"],
            name="fk_iiko_document_writes_supply_request",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supply_request_id",
            "source_store_id",
            "document_type",
            name="uq_iiko_document_writes_request_source_type",
        ),
        sa.UniqueConstraint(
            "iiko_document_id",
            name="uq_iiko_document_writes_iiko_document_id",
        ),
    )
    op.create_index(
        "ix_iiko_document_writes_status_updated",
        "iiko_document_writes",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_iiko_document_writes_status_updated",
        table_name="iiko_document_writes",
    )
    op.drop_table("iiko_document_writes")
