"""add supply simple working values

Revision ID: 20260728_0017
Revises: 20260727_0016
Create Date: 2026-07-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_0017"
down_revision: Union[str, Sequence[str], None] = "20260727_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "supply_request_lines",
        sa.Column("working_name_override", sa.Text(), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("send_quantity", sa.Numeric(18, 3), nullable=True),
    )
    op.create_check_constraint(
        "ck_supply_request_lines_send_quantity_nonnegative",
        "supply_request_lines",
        "send_quantity IS NULL OR send_quantity >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_supply_request_lines_send_quantity_nonnegative",
        "supply_request_lines",
        type_="check",
    )
    op.drop_column("supply_request_lines", "send_quantity")
    op.drop_column("supply_request_lines", "working_name_override")
