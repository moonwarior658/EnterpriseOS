"""add acceptance destination mapping

Revision ID: 20260917_0050
Revises: 20260917_0049
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260917_0050"
down_revision: str | None = "20260917_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "supply_supplier_acceptances",
        sa.Column("destination_mapping_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_supply_supplier_acceptances_destination_tenant",
        "supply_supplier_acceptances",
        "iiko_warehouse_mappings",
        ["tenant_id", "destination_mapping_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_supply_supplier_acceptances_destination",
        "supply_supplier_acceptances",
        ["tenant_id", "destination_mapping_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_supplier_acceptances_destination",
        table_name="supply_supplier_acceptances",
    )
    op.drop_constraint(
        "fk_supply_supplier_acceptances_destination_tenant",
        "supply_supplier_acceptances",
        type_="foreignkey",
    )
    op.drop_column("supply_supplier_acceptances", "destination_mapping_id")
