"""add Supply request iiko source warehouse

Revision ID: 20260803_0024
Revises: 20260802_0023
Create Date: 2026-08-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260803_0024"
down_revision: Union[str, Sequence[str], None] = "20260802_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "supply_requests",
        sa.Column(
            "iiko_source_warehouse_mapping_id",
            sa.Uuid(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_supply_requests_iiko_source_warehouse_mapping",
        "supply_requests",
        "iiko_warehouse_mappings",
        ["iiko_source_warehouse_mapping_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_supply_requests_iiko_source_warehouse_mapping",
        "supply_requests",
        type_="foreignkey",
    )
    op.drop_column(
        "supply_requests",
        "iiko_source_warehouse_mapping_id",
    )
