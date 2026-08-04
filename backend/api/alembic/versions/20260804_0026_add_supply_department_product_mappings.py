"""add contextual Supply product mappings

Revision ID: 20260804_0026
Revises: 20260803_0025
Create Date: 2026-08-04
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "20260804_0026"
down_revision: Union[str, Sequence[str], None] = "20260803_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_supply_request_lines_match_method",
        "supply_request_lines",
        type_="check",
    )
    op.create_check_constraint(
        "ck_supply_request_lines_match_method",
        "supply_request_lines",
        "match_method IS NULL OR match_method IN "
        "('CONTEXT_MAPPING', 'EXACT_PRODUCT', 'EXACT_ALIAS', 'MANUAL')",
    )
    op.create_unique_constraint(
        "uq_departments_tenant_id",
        "departments",
        ["tenant_id", "id"],
    )
    op.create_unique_constraint(
        "uq_supply_products_tenant_id",
        "supply_products",
        ["tenant_id", "id"],
    )
    op.create_table(
        "supply_department_product_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("phrase", sa.String(length=240), nullable=False),
        sa.Column("normalized_phrase", sa.String(length=240), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("is_permanent", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_supply_context_mapping_tenant_department",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["supply_products.tenant_id", "supply_products.id"],
            name="fk_supply_context_mapping_tenant_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "version >= 1", name="ck_supply_context_mapping_version"
        ),
        sa.UniqueConstraint("tenant_id", "department_id", "normalized_phrase", name="uq_supply_department_product_mapping_context"),
    )
    op.create_index(
        "ix_supply_department_product_mapping_phrase",
        "supply_department_product_mappings",
        ["tenant_id", "normalized_phrase"],
    )
    op.create_table(
        "supply_department_product_corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_phrase", sa.String(length=240), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("request_line_id", sa.Uuid(), nullable=False),
        sa.Column("corrected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_supply_context_correction_tenant_department",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["supply_products.tenant_id", "supply_products.id"],
            name="fk_supply_context_correction_tenant_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["request_line_id"], ["supply_request_lines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["corrected_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_line_id", "product_id", name="uq_supply_department_product_correction_line_product"),
    )
    op.create_index(
        "ix_supply_department_product_correction_count",
        "supply_department_product_corrections",
        ["tenant_id", "department_id", "normalized_phrase", "product_id"],
    )
    op.create_table(
        "supply_department_product_mapping_audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("mapping_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Enum("CREATED", "REPLACED", "DELETED", name="supply_context_mapping_audit_action", native_enum=False, create_constraint=True, length=16), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_phrase", sa.String(length=240), nullable=False),
        sa.Column("previous_product_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_supply_context_audit_tenant_department",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supply_department_product_mapping_audit",
        "supply_department_product_mapping_audit_events",
        ["tenant_id", "mapping_id", "created_at"],
    )

def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE supply_request_lines
        SET match_method = 'MANUAL'
        WHERE match_method = 'CONTEXT_MAPPING'
    """))
    op.drop_index("ix_supply_department_product_mapping_audit", table_name="supply_department_product_mapping_audit_events")
    op.drop_table("supply_department_product_mapping_audit_events")
    op.drop_index("ix_supply_department_product_correction_count", table_name="supply_department_product_corrections")
    op.drop_table("supply_department_product_corrections")
    op.drop_index("ix_supply_department_product_mapping_phrase", table_name="supply_department_product_mappings")
    op.drop_table("supply_department_product_mappings")
    op.drop_constraint(
        "uq_supply_products_tenant_id",
        "supply_products",
        type_="unique",
    )
    op.drop_constraint(
        "uq_departments_tenant_id",
        "departments",
        type_="unique",
    )
    op.drop_constraint(
        "ck_supply_request_lines_match_method",
        "supply_request_lines",
        type_="check",
    )
    op.create_check_constraint(
        "ck_supply_request_lines_match_method",
        "supply_request_lines",
        "match_method IS NULL OR match_method IN "
        "('EXACT_PRODUCT', 'EXACT_ALIAS', 'MANUAL')",
    )
