"""add supplier minimum order amount

Revision ID: 20260914_0042
Revises: 20260914_0041
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_0042"
down_revision: Union[str, Sequence[str], None] = "20260914_0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("supply_suppliers") as batch_op:
        batch_op.add_column(
            sa.Column("minimum_order_amount", sa.Numeric(18, 2), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_supply_suppliers_minimum_order_amount",
            "minimum_order_amount IS NULL OR minimum_order_amount >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("supply_suppliers") as batch_op:
        batch_op.drop_constraint(
            "ck_supply_suppliers_minimum_order_amount", type_="check"
        )
        batch_op.drop_column("minimum_order_amount")
