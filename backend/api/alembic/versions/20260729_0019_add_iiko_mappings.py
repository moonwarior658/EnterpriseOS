"""add explicit iiko to EOS mappings

Revision ID: 20260729_0019
Revises: 20260729_0018
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260729_0019"
down_revision: Union[str, Sequence[str], None] = "20260729_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MAPPING_STATUSES = (
    "UNMAPPED",
    "SUGGESTED",
    "CONFIRMED",
    "CONFLICT",
    "IGNORED",
)
WAREHOUSE_ROLES = (
    "MAIN",
    "PACKAGING",
    "HOUSEHOLD",
    "FIXED_ASSETS",
    "OTHER",
)
MAPPING_KINDS = ("PRODUCT", "UNIT", "WAREHOUSE")
MAPPING_ACTIONS = (
    "GENERATED",
    "CONFIRMED",
    "REPLACED",
    "IGNORED",
    "UNMAPPED",
)


def mapping_status(name: str) -> sa.Enum:
    return sa.Enum(
        *MAPPING_STATUSES,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
    )


def common_columns(external_name: str) -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(external_name, sa.Uuid(), nullable=False),
    ]


def decision_columns(status_name: str) -> list[sa.Column]:
    return [
        sa.Column("status", mapping_status(status_name), nullable=False),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column(
            "reasons",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.create_table(
        "iiko_product_mappings",
        *common_columns("iiko_product_id"),
        sa.Column("eos_product_id", sa.Uuid(), nullable=True),
        sa.Column("source_name", sa.String(length=240), nullable=False),
        sa.Column("source_code", sa.String(length=160), nullable=True),
        sa.Column("source_sku", sa.String(length=160), nullable=True),
        sa.Column("source_unit_id", sa.Uuid(), nullable=True),
        *decision_columns("ck_iiko_product_mapping_status"),
        sa.ForeignKeyConstraint(
            ["eos_product_id"],
            ["supply_products.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "iiko_product_id",
            name="uq_iiko_product_mappings_tenant_external",
        ),
    )
    op.create_index(
        "ix_iiko_product_mappings_queue",
        "iiko_product_mappings",
        ["tenant_id", "status", "is_deleted", "source_name"],
    )
    op.create_index(
        "uq_iiko_product_mappings_confirmed_eos",
        "iiko_product_mappings",
        ["tenant_id", "eos_product_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'CONFIRMED' AND is_deleted = false "
            "AND eos_product_id IS NOT NULL"
        ),
    )

    op.create_table(
        "iiko_unit_mappings",
        *common_columns("iiko_unit_id"),
        sa.Column("eos_unit_id", sa.Uuid(), nullable=True),
        sa.Column("source_name", sa.String(length=160), nullable=False),
        sa.Column("source_code", sa.String(length=80), nullable=True),
        *decision_columns("ck_iiko_unit_mapping_status"),
        sa.ForeignKeyConstraint(
            ["eos_unit_id"],
            ["supply_units.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "iiko_unit_id",
            name="uq_iiko_unit_mappings_tenant_external",
        ),
    )
    op.create_index(
        "ix_iiko_unit_mappings_queue",
        "iiko_unit_mappings",
        ["tenant_id", "status", "is_deleted", "source_name"],
    )
    op.create_index(
        "uq_iiko_unit_mappings_confirmed_eos",
        "iiko_unit_mappings",
        ["tenant_id", "eos_unit_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'CONFIRMED' AND is_deleted = false "
            "AND eos_unit_id IS NOT NULL"
        ),
    )

    op.create_table(
        "iiko_warehouse_mappings",
        *common_columns("iiko_warehouse_id"),
        sa.Column("eos_department_id", sa.Uuid(), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                *WAREHOUSE_ROLES,
                name="ck_iiko_warehouse_mapping_role",
                native_enum=False,
                create_constraint=True,
                length=24,
            ),
            nullable=True,
        ),
        sa.Column("source_name", sa.String(length=240), nullable=False),
        sa.Column("source_code", sa.String(length=160), nullable=True),
        *decision_columns("ck_iiko_warehouse_mapping_status"),
        sa.ForeignKeyConstraint(
            ["eos_department_id"],
            ["departments.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "iiko_warehouse_id",
            name="uq_iiko_warehouse_mappings_tenant_external",
        ),
    )
    op.create_index(
        "ix_iiko_warehouse_mappings_queue",
        "iiko_warehouse_mappings",
        ["tenant_id", "status", "is_deleted", "source_name"],
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

    op.create_table(
        "iiko_mapping_audit_events",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "mapping_kind",
            sa.Enum(
                *MAPPING_KINDS,
                name="ck_iiko_mapping_audit_kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("mapping_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                *MAPPING_ACTIONS,
                name="ck_iiko_mapping_audit_action",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "before",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "after",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_iiko_mapping_audit_tenant_mapping",
        "iiko_mapping_audit_events",
        ["tenant_id", "mapping_kind", "mapping_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_iiko_mapping_audit_tenant_mapping",
        table_name="iiko_mapping_audit_events",
    )
    op.drop_table("iiko_mapping_audit_events")
    op.drop_index(
        "uq_iiko_warehouse_mappings_confirmed_role",
        table_name="iiko_warehouse_mappings",
    )
    op.drop_index(
        "ix_iiko_warehouse_mappings_queue",
        table_name="iiko_warehouse_mappings",
    )
    op.drop_table("iiko_warehouse_mappings")
    op.drop_index(
        "uq_iiko_unit_mappings_confirmed_eos",
        table_name="iiko_unit_mappings",
    )
    op.drop_index(
        "ix_iiko_unit_mappings_queue",
        table_name="iiko_unit_mappings",
    )
    op.drop_table("iiko_unit_mappings")
    op.drop_index(
        "uq_iiko_product_mappings_confirmed_eos",
        table_name="iiko_product_mappings",
    )
    op.drop_index(
        "ix_iiko_product_mappings_queue",
        table_name="iiko_product_mappings",
    )
    op.drop_table("iiko_product_mappings")
