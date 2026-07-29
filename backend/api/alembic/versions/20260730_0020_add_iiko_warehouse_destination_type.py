"""add iiko warehouse destination type and source priority

Revision ID: 20260730_0020
Revises: 20260729_0019
Create Date: 2026-07-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0020"
down_revision: Union[str, Sequence[str], None] = "20260729_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DESTINATION_TYPES = ("DESTINATION", "SOURCE")
SOURCE_DIRECTIONS = (
    "PRODUCT",
    "PACKAGING",
    "HOUSEHOLD",
    "FIXED_ASSETS",
)


def upgrade() -> None:
    op.add_column(
        "iiko_warehouse_mappings",
        sa.Column(
            "destination_type",
            sa.Enum(
                *DESTINATION_TYPES,
                name="ck_iiko_warehouse_mapping_destination_type",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="DESTINATION",
            nullable=False,
        ),
    )
    op.add_column(
        "iiko_warehouse_mappings",
        sa.Column(
            "source_direction",
            sa.Enum(
                *SOURCE_DIRECTIONS,
                name="ck_iiko_warehouse_mapping_source_direction",
                native_enum=False,
                create_constraint=True,
                length=24,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "iiko_warehouse_mappings",
        sa.Column("source_priority", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_iiko_warehouse_mapping_source_priority_positive",
        "iiko_warehouse_mappings",
        "source_priority IS NULL OR source_priority >= 1",
    )
    op.create_check_constraint(
        "ck_iiko_warehouse_mapping_confirmed_target",
        "iiko_warehouse_mappings",
        "status != 'CONFIRMED' OR "
        "(destination_type = 'DESTINATION' "
        "AND eos_department_id IS NOT NULL AND role IS NOT NULL "
        "AND source_direction IS NULL AND source_priority IS NULL) OR "
        "(destination_type = 'SOURCE' "
        "AND eos_department_id IS NULL AND role IS NULL "
        "AND source_direction IS NOT NULL AND source_priority IS NOT NULL)",
    )
    op.drop_index(
        "uq_iiko_warehouse_mappings_confirmed_role",
        table_name="iiko_warehouse_mappings",
    )
    op.create_index(
        "uq_iiko_warehouse_mappings_confirmed_role",
        "iiko_warehouse_mappings",
        ["tenant_id", "eos_department_id", "role"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'CONFIRMED' "
            "AND destination_type = 'DESTINATION' "
            "AND eos_department_id IS NOT NULL "
            "AND role IS NOT NULL AND is_deleted = false"
        ),
    )
    op.create_index(
        "uq_iiko_warehouse_mappings_confirmed_source_priority",
        "iiko_warehouse_mappings",
        ["tenant_id", "source_direction", "source_priority"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'CONFIRMED' AND destination_type = 'SOURCE' "
            "AND source_direction IS NOT NULL "
            "AND source_priority IS NOT NULL AND is_deleted = false"
        ),
    )
    op.alter_column(
        "iiko_warehouse_mappings",
        "destination_type",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_iiko_warehouse_mappings_confirmed_source_priority",
        table_name="iiko_warehouse_mappings",
    )
    op.drop_index(
        "uq_iiko_warehouse_mappings_confirmed_role",
        table_name="iiko_warehouse_mappings",
    )
    op.create_index(
        "uq_iiko_warehouse_mappings_confirmed_role",
        "iiko_warehouse_mappings",
        ["tenant_id", "eos_department_id", "role"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'CONFIRMED' AND eos_department_id IS NOT NULL "
            "AND role IS NOT NULL AND is_deleted = false"
        ),
    )
    op.drop_constraint(
        "ck_iiko_warehouse_mapping_confirmed_target",
        "iiko_warehouse_mappings",
        type_="check",
    )
    op.drop_constraint(
        "ck_iiko_warehouse_mapping_source_priority_positive",
        "iiko_warehouse_mappings",
        type_="check",
    )
    op.drop_column("iiko_warehouse_mappings", "source_priority")
    op.drop_column("iiko_warehouse_mappings", "source_direction")
    op.drop_column("iiko_warehouse_mappings", "destination_type")
