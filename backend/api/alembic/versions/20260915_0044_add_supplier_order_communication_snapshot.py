"""add supplier order communication snapshot

Revision ID: 20260915_0044
Revises: 20260915_0043
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_0044"
down_revision: Union[str, Sequence[str], None] = "20260915_0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("supply_supplier_orders", sa.Column("recipient_email_snapshot", sa.String(length=320), nullable=True))
    op.add_column("supply_supplier_orders", sa.Column("recipient_name_snapshot", sa.String(length=240), nullable=True))
    op.add_column("supply_supplier_orders", sa.Column("responsible_name_snapshot", sa.String(length=128), nullable=True))
    op.add_column("supply_supplier_orders", sa.Column("responsible_phone_snapshot", sa.String(length=40), nullable=True))
    op.create_check_constraint(
        "ck_supply_supplier_orders_communication_snapshot",
        "supply_supplier_orders",
        "(recipient_email_snapshot IS NULL AND recipient_name_snapshot IS NULL "
        "AND responsible_name_snapshot IS NULL AND responsible_phone_snapshot IS NULL) OR "
        "(recipient_email_snapshot IS NOT NULL AND recipient_name_snapshot IS NOT NULL "
        "AND responsible_name_snapshot IS NOT NULL AND responsible_phone_snapshot IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_supply_supplier_orders_communication_snapshot", "supply_supplier_orders", type_="check")
    op.drop_column("supply_supplier_orders", "responsible_phone_snapshot")
    op.drop_column("supply_supplier_orders", "responsible_name_snapshot")
    op.drop_column("supply_supplier_orders", "recipient_name_snapshot")
    op.drop_column("supply_supplier_orders", "recipient_email_snapshot")
