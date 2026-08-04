"""add Supply product source mappings

Revision ID: 20260803_0025
Revises: 20260803_0024
Create Date: 2026-08-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260803_0025"
down_revision: Union[str, Sequence[str], None] = "20260803_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_product_source_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("eos_product_id", sa.Uuid(), nullable=False),
        sa.Column(
            "legal_contour",
            sa.Enum(
                "IP", "OOO",
                name="supply_product_source_legal_contour",
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum(
                "MAIN", "PACKAGING", "HOUSEHOLD",
                name="supply_product_source_role",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("source_warehouse_mapping_id", sa.Uuid(), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["eos_product_id"], ["supply_products.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_warehouse_mapping_id"],
            ["iiko_warehouse_mappings.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_supply_product_source_mapping_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "eos_product_id", "legal_contour",
            name="uq_supply_product_source_mapping_product_contour",
        ),
    )
    op.create_index(
        "ix_supply_product_source_mapping_source",
        "supply_product_source_mappings",
        ["tenant_id", "source_warehouse_mapping_id"],
    )
    op.create_table(
        "supply_product_source_mapping_audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("mapping_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "BOOTSTRAPPED", "ASSIGNED", "REPLACED",
                name="supply_product_source_audit_action",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "previous_source_warehouse_mapping_id", sa.Uuid(), nullable=True
        ),
        sa.Column("source_warehouse_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["mapping_id"], ["supply_product_source_mappings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supply_product_source_audit_mapping_created",
        "supply_product_source_mapping_audit_events",
        ["tenant_id", "mapping_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_product_source_audit_mapping_created",
        table_name="supply_product_source_mapping_audit_events",
    )
    op.drop_table("supply_product_source_mapping_audit_events")
    op.drop_index(
        "ix_supply_product_source_mapping_source",
        table_name="supply_product_source_mappings",
    )
    op.drop_table("supply_product_source_mappings")
