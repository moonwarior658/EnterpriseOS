"""add warehouse legal contours

Revision ID: 20260730_0021
Revises: 20260730_0020
Create Date: 2026-07-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0021"
down_revision: Union[str, Sequence[str], None] = "20260730_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGAL_CONTOURS = ("IP", "OOO")
SOURCE_DIRECTIONS = (
    "PRODUCT",
    "PACKAGING",
    "HOUSEHOLD",
    "FIXED_ASSETS",
)


def legal_contour_enum(name: str) -> sa.Enum:
    return sa.Enum(
        *LEGAL_CONTOURS,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=8,
    )


def upgrade() -> None:
    op.add_column(
        "departments",
        sa.Column(
            "legal_contour",
            legal_contour_enum("ck_department_legal_contour"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO departments
                (id, tenant_id, code, name, legal_contour,
                 is_active, display_order)
            VALUES
                ('b4a1a8c9-b1f5-46e2-b928-361cd222f042', 'eclair',
                 'КУХНЯ', 'Кухня', 'OOO', true, 50),
                ('fe9d9719-9ef6-42dc-8ee1-54c4dc3da253', 'eclair',
                 'БАР ГХ', 'Бар ГХ', 'OOO', true, 60)
            ON CONFLICT (tenant_id, code) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            "UPDATE departments SET legal_contour = 'IP' "
            "WHERE tenant_id = 'eclair' "
            "AND code IN ('ЦЕХ', 'М15', 'М35', 'М6А')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE departments SET legal_contour = 'OOO' "
            "WHERE tenant_id = 'eclair' "
            "AND (code IN ('КУХНЯ', 'БАР ГХ') "
            "OR name IN ('Кухня', 'Бар ГХ'))"
        )
    )
    op.add_column(
        "iiko_warehouse_mappings",
        sa.Column(
            "legal_contour",
            legal_contour_enum(
                "ck_iiko_warehouse_mapping_legal_contour"
            ),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE iiko_warehouse_mappings "
            "SET status = 'UNMAPPED', confidence = NULL "
            "WHERE destination_type = 'SOURCE'"
        )
    )
    op.drop_index(
        "uq_iiko_warehouse_mappings_confirmed_source_priority",
        table_name="iiko_warehouse_mappings",
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
    op.execute(
        sa.text(
            "UPDATE iiko_mapping_audit_events "
            "SET before = before - 'source_priority' - 'source_direction', "
            "after = after - 'source_priority' - 'source_direction' "
            "WHERE mapping_kind = 'WAREHOUSE'"
        )
    )
    op.create_check_constraint(
        "ck_iiko_warehouse_mapping_confirmed_target",
        "iiko_warehouse_mappings",
        "status != 'CONFIRMED' OR "
        "(destination_type = 'DESTINATION' "
        "AND eos_department_id IS NOT NULL AND role IS NOT NULL "
        "AND legal_contour IS NULL) OR "
        "(destination_type = 'SOURCE' "
        "AND eos_department_id IS NULL AND role IS NOT NULL "
        "AND legal_contour IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_iiko_warehouse_mapping_confirmed_target",
        "iiko_warehouse_mappings",
        type_="check",
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
    op.drop_column("iiko_warehouse_mappings", "legal_contour")
    op.drop_column("departments", "legal_contour")
