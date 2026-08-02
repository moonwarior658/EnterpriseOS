"""allow supply overfulfillment

Revision ID: 20260802_0022
Revises: 20260730_0021
Create Date: 2026-08-02
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260802_0022"
down_revision: Union[str, Sequence[str], None] = "20260730_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "ck_supply_line_allocations_fulfilled_quantity"


def upgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "supply_line_allocations",
        type_="check",
    )
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "supply_line_allocations",
        "fulfilled_quantity >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "supply_line_allocations",
        type_="check",
    )
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "supply_line_allocations",
        "fulfilled_quantity >= 0 AND fulfilled_quantity <= planned_quantity",
    )
