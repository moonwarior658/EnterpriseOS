"""add immutable iiko stock balance snapshots

Revision ID: 20260805_0028
Revises: 20260804_0027
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260805_0028"
down_revision: Union[str, Sequence[str], None] = "20260804_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_SYNC_TYPES = (
    "CONNECTION_CHECK",
    "ORGANIZATIONS",
    "ENTERPRISES",
    "WAREHOUSES",
    "PRODUCT_GROUPS",
    "PRODUCTS",
    "UNITS",
    "PACKAGES",
    "STOCK_BALANCES",
    "FULL_REFERENCE_SNAPSHOT",
)
NEW_SYNC_TYPES = (*OLD_SYNC_TYPES[:-1], "STOCK_BALANCE_SNAPSHOT", OLD_SYNC_TYPES[-1])


def _sync_type_expression(values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"sync_type IN ({allowed})"


def upgrade() -> None:
    op.drop_constraint("iiko_sync_type", "iiko_sync_runs", type_="check")
    op.create_check_constraint(
        "iiko_sync_type",
        "iiko_sync_runs",
        _sync_type_expression(NEW_SYNC_TYPES),
    )
    op.create_unique_constraint(
        "uq_iiko_sync_runs_tenant_id",
        "iiko_sync_runs",
        ["tenant_id", "id"],
    )
    op.create_table(
        "iiko_stock_balance_snapshot_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("source_warehouse_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SUCCEEDED",
                "FAILED",
                name="iiko_stock_snapshot_source_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_iiko_stock_snapshot_tenant_department",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_warehouse_mapping_id"],
            ["iiko_warehouse_mappings.tenant_id", "iiko_warehouse_mappings.id"],
            name="fk_iiko_stock_snapshot_tenant_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sync_run_id"],
            ["iiko_sync_runs.tenant_id", "iiko_sync_runs.id"],
            name="fk_iiko_stock_snapshot_tenant_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sync_run_id",
            "source_warehouse_mapping_id",
            name="uq_iiko_stock_snapshot_source_run_source",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "sync_run_id",
            "department_id",
            "source_warehouse_mapping_id",
            name="uq_iiko_stock_snapshot_source_tenant_scope",
        ),
    )
    op.create_index(
        "ix_iiko_stock_snapshot_source_latest",
        "iiko_stock_balance_snapshot_sources",
        ["tenant_id", "source_warehouse_mapping_id", "status", "snapshot_at"],
    )
    op.create_table(
        "iiko_stock_balance_snapshot_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("source_warehouse_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_product_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "sync_run_id",
                "department_id",
                "source_warehouse_mapping_id",
            ],
            [
                "iiko_stock_balance_snapshot_sources.tenant_id",
                "iiko_stock_balance_snapshot_sources.sync_run_id",
                "iiko_stock_balance_snapshot_sources.department_id",
                "iiko_stock_balance_snapshot_sources.source_warehouse_mapping_id",
            ],
            name="fk_iiko_stock_snapshot_line_source_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sync_run_id",
            "source_warehouse_mapping_id",
            "iiko_product_id",
            name="uq_iiko_stock_snapshot_run_source_product",
        ),
    )
    op.create_index(
        "ix_iiko_stock_snapshot_line_run_product",
        "iiko_stock_balance_snapshot_lines",
        ["tenant_id", "sync_run_id", "iiko_product_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    snapshot_run_count = bind.scalar(sa.text("""
        SELECT count(*)
        FROM iiko_sync_runs
        WHERE sync_type = 'STOCK_BALANCE_SNAPSHOT'
    """))
    if snapshot_run_count:
        raise RuntimeError(
            "Cannot downgrade while STOCK_BALANCE_SNAPSHOT runs exist"
        )
    op.drop_index(
        "ix_iiko_stock_snapshot_line_run_product",
        table_name="iiko_stock_balance_snapshot_lines",
    )
    op.drop_table("iiko_stock_balance_snapshot_lines")
    op.drop_index(
        "ix_iiko_stock_snapshot_source_latest",
        table_name="iiko_stock_balance_snapshot_sources",
    )
    op.drop_table("iiko_stock_balance_snapshot_sources")
    op.drop_constraint(
        "uq_iiko_sync_runs_tenant_id",
        "iiko_sync_runs",
        type_="unique",
    )
    op.drop_constraint("iiko_sync_type", "iiko_sync_runs", type_="check")
    op.create_check_constraint(
        "iiko_sync_type",
        "iiko_sync_runs",
        _sync_type_expression(OLD_SYNC_TYPES),
    )
