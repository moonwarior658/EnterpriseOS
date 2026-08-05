"""add tenant-safe persisted Supply stock calculations

Revision ID: 20260804_0027
Revises: 20260804_0026
Create Date: 2026-08-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260804_0027"
down_revision: Union[str, Sequence[str], None] = "20260804_0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_supply_requests_tenant_id",
        "supply_requests",
        ["tenant_id", "id"],
    )
    op.create_unique_constraint(
        "uq_supply_units_tenant_id",
        "supply_units",
        ["tenant_id", "id"],
    )
    op.create_unique_constraint(
        "uq_iiko_warehouse_mappings_tenant_id",
        "iiko_warehouse_mappings",
        ["tenant_id", "id"],
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
    )
    op.execute(sa.text("""
        UPDATE supply_request_lines AS line
        SET tenant_id = request.tenant_id
        FROM supply_requests AS request
        WHERE request.id = line.request_id
    """))
    op.alter_column(
        "supply_request_lines",
        "tenant_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_supply_request_lines_tenant_id",
        "supply_request_lines",
        ["tenant_id", "id"],
    )
    op.create_unique_constraint(
        "uq_supply_request_lines_tenant_request_id",
        "supply_request_lines",
        ["tenant_id", "request_id", "id"],
    )
    op.drop_constraint(
        "supply_request_lines_request_id_fkey",
        "supply_request_lines",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_supply_request_lines_tenant_request",
        "supply_request_lines",
        "supply_requests",
        ["tenant_id", "request_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "supply_stock_calculations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PRELIMINARY", "CONFIRMED",
                name="supply_stock_calculation_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calculated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_supply_stock_calculation_revision"
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_supply_stock_calculation_version"
        ),
        sa.CheckConstraint(
            "(status = 'PRELIMINARY' AND confirmed_at IS NULL "
            "AND confirmed_by_user_id IS NULL) OR "
            "(status = 'CONFIRMED' AND confirmed_at IS NOT NULL "
            "AND confirmed_by_user_id IS NOT NULL)",
            name="ck_supply_stock_calculation_confirmation_state",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["supply_requests.tenant_id", "supply_requests.id"],
            name="fk_supply_stock_calculation_tenant_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["calculated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "request_id", "revision",
            name="uq_supply_stock_calculation_request_revision",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id",
            name="uq_supply_stock_calculation_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", "request_id",
            name="uq_supply_stock_calculation_tenant_id_request",
        ),
    )
    op.create_index(
        "ix_supply_stock_calculation_request_revision",
        "supply_stock_calculations",
        ["request_id", "revision"],
    )
    op.create_table(
        "supply_stock_calculation_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("calculation_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_line_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(length=240), nullable=False),
        sa.Column("requested_unit_id", sa.Uuid(), nullable=True),
        sa.Column("requested_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("source_warehouse_mapping_id", sa.Uuid(), nullable=True),
        sa.Column("source_name", sa.String(length=240), nullable=True),
        sa.Column("iiko_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("transferable_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("deficit_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("unavailable_reason", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "requested_quantity IS NULL OR requested_quantity >= 0",
            name="ck_supply_stock_calculation_line_requested_nonnegative",
        ),
        sa.CheckConstraint(
            "transferable_quantity IS NULL OR transferable_quantity >= 0",
            name="ck_supply_stock_calculation_line_transferable_nonnegative",
        ),
        sa.CheckConstraint(
            "deficit_quantity IS NULL OR deficit_quantity >= 0",
            name="ck_supply_stock_calculation_line_deficit_nonnegative",
        ),
        sa.CheckConstraint(
            "transferable_quantity IS NULL OR "
            "transferable_quantity <= requested_quantity",
            name="ck_supply_stock_calculation_line_transferable_requested",
        ),
        sa.CheckConstraint(
            "(unavailable_reason IS NOT NULL "
            "AND transferable_quantity IS NULL AND deficit_quantity IS NULL) "
            "OR (unavailable_reason IS NULL "
            "AND requested_quantity IS NOT NULL "
            "AND available_quantity IS NOT NULL "
            "AND transferable_quantity IS NOT NULL "
            "AND deficit_quantity IS NOT NULL "
            "AND deficit_quantity = requested_quantity - transferable_quantity)",
            name="ck_supply_stock_calculation_line_state",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_supply_stock_calculation_line_version"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calculation_id", "request_id"],
            [
                "supply_stock_calculations.tenant_id",
                "supply_stock_calculations.id",
                "supply_stock_calculations.request_id",
            ],
            name="fk_supply_stock_line_tenant_calculation_request",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id", "request_line_id"],
            [
                "supply_request_lines.tenant_id",
                "supply_request_lines.request_id",
                "supply_request_lines.id",
            ],
            name="fk_supply_stock_line_tenant_request_line",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["supply_products.tenant_id", "supply_products.id"],
            name="fk_supply_stock_line_tenant_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_unit_id"],
            ["supply_units.tenant_id", "supply_units.id"],
            name="fk_supply_stock_line_tenant_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_warehouse_mapping_id"],
            ["iiko_warehouse_mappings.tenant_id", "iiko_warehouse_mappings.id"],
            name="fk_supply_stock_line_tenant_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "calculation_id", "request_line_id",
            name="uq_supply_stock_calculation_line_request_line",
        ),
        sa.UniqueConstraint(
            "tenant_id", "calculation_id", "id",
            name="uq_supply_stock_calculation_line_tenant_calculation_id",
        ),
    )
    op.create_index(
        "ix_supply_stock_calculation_line_position",
        "supply_stock_calculation_lines",
        ["calculation_id", "position"],
    )
    op.create_table(
        "supply_stock_calculation_audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("calculation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "AUTO_CALCULATED", "MANUALLY_ADJUSTED", "CONFIRMED",
                "RECALCULATED",
                name="supply_stock_calculation_audit_action",
                native_enum=False,
                create_constraint=True,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("calculation_line_id", sa.Uuid(), nullable=True),
        sa.Column("previous_quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calculation_id"],
            [
                "supply_stock_calculations.tenant_id",
                "supply_stock_calculations.id",
            ],
            name="fk_supply_stock_audit_tenant_calculation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calculation_id", "calculation_line_id"],
            [
                "supply_stock_calculation_lines.tenant_id",
                "supply_stock_calculation_lines.calculation_id",
                "supply_stock_calculation_lines.id",
            ],
            name="fk_supply_stock_audit_tenant_calculation_line",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supply_stock_calculation_audit_created",
        "supply_stock_calculation_audit_events",
        ["tenant_id", "calculation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_stock_calculation_audit_created",
        table_name="supply_stock_calculation_audit_events",
    )
    op.drop_table("supply_stock_calculation_audit_events")
    op.drop_index(
        "ix_supply_stock_calculation_line_position",
        table_name="supply_stock_calculation_lines",
    )
    op.drop_table("supply_stock_calculation_lines")
    op.drop_index(
        "ix_supply_stock_calculation_request_revision",
        table_name="supply_stock_calculations",
    )
    op.drop_table("supply_stock_calculations")

    op.drop_constraint(
        "fk_supply_request_lines_tenant_request",
        "supply_request_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_supply_request_lines_tenant_request_id",
        "supply_request_lines",
        type_="unique",
    )
    op.drop_constraint(
        "uq_supply_request_lines_tenant_id",
        "supply_request_lines",
        type_="unique",
    )
    op.drop_column("supply_request_lines", "tenant_id")
    op.create_foreign_key(
        "supply_request_lines_request_id_fkey",
        "supply_request_lines",
        "supply_requests",
        ["request_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "uq_iiko_warehouse_mappings_tenant_id",
        "iiko_warehouse_mappings",
        type_="unique",
    )
    op.drop_constraint(
        "uq_supply_units_tenant_id",
        "supply_units",
        type_="unique",
    )
    op.drop_constraint(
        "uq_supply_requests_tenant_id",
        "supply_requests",
        type_="unique",
    )
