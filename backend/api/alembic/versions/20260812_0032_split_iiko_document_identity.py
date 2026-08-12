"""split caller and authoritative iiko document identities

Revision ID: 20260812_0032
Revises: 20260811_0031
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0032"
down_revision: Union[str, Sequence[str], None] = "20260811_0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("iiko_document_writes") as batch_op:
        batch_op.drop_constraint(
            "uq_iiko_document_writes_iiko_document_id",
            type_="unique",
        )
        batch_op.alter_column(
            "iiko_document_id",
            new_column_name="client_document_id",
            existing_type=sa.Uuid(),
            existing_nullable=False,
        )
    with op.batch_alter_table("iiko_document_writes") as batch_op:
        batch_op.add_column(
            sa.Column("iiko_document_id", sa.Uuid(), nullable=True)
        )
    with op.batch_alter_table("iiko_document_writes") as batch_op:
        batch_op.create_unique_constraint(
            "uq_iiko_document_writes_client_document_id",
            ["client_document_id"],
        )
        batch_op.create_unique_constraint(
            "uq_iiko_document_writes_iiko_document_id",
            ["iiko_document_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("iiko_document_writes") as batch_op:
        batch_op.drop_constraint(
            "uq_iiko_document_writes_iiko_document_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "uq_iiko_document_writes_client_document_id",
            type_="unique",
        )
    with op.batch_alter_table("iiko_document_writes") as batch_op:
        batch_op.drop_column("iiko_document_id")
    with op.batch_alter_table("iiko_document_writes") as batch_op:
        batch_op.alter_column(
            "client_document_id",
            new_column_name="iiko_document_id",
            existing_type=sa.Uuid(),
            existing_nullable=False,
        )
    with op.batch_alter_table("iiko_document_writes") as batch_op:
        batch_op.create_unique_constraint(
            "uq_iiko_document_writes_iiko_document_id",
            ["iiko_document_id"],
        )
