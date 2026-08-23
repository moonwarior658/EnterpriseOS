"""add internal transfer document type

Revision ID: 20260824_0034
Revises: 20260812_0033
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260824_0034"
down_revision: Union[str, Sequence[str], None] = "20260812_0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_document_type_constraint(values: tuple[str, ...]) -> None:
    with op.batch_alter_table("iiko_document_writes") as batch_op:
        batch_op.drop_constraint("iiko_document_type", type_="check")
        batch_op.create_check_constraint(
            "iiko_document_type",
            "document_type IN ({})".format(
                ", ".join(f"'{value}'" for value in values)
            ),
        )


def upgrade() -> None:
    _replace_document_type_constraint((
        "OUTGOING_INVOICE",
        "INTERNAL_TRANSFER",
    ))


def downgrade() -> None:
    connection = op.get_bind()
    internal_transfers = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM iiko_document_writes "
        "WHERE document_type = 'INTERNAL_TRANSFER'"
    ).scalar_one()
    if internal_transfers:
        raise RuntimeError(
            "Cannot remove INTERNAL_TRANSFER while document writes exist"
        )
    _replace_document_type_constraint(("OUTGOING_INVOICE",))
