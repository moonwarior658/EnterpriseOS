"""add iiko read-only staging and sync history

Revision ID: 20260729_0018
Revises: 20260728_0017
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260729_0018"
down_revision: Union[str, Sequence[str], None] = "20260728_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SYNC_TYPES = (
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
SYNC_STATUSES = (
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "PARTIALLY_SUCCEEDED",
    "FAILED",
    "CANCELLED",
)


def upgrade() -> None:
    op.create_table(
        "iiko_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "sync_type",
            sa.Enum(
                *SYNC_TYPES,
                name="iiko_sync_type",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                *SYNC_STATUSES,
                name="iiko_sync_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("source_api_type", sa.String(length=40), nullable=False),
        sa.Column(
            "source_organization_id",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "parameters",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "records_received",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "records_created",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "records_updated",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "records_unchanged",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "records_failed",
            sa.Integer(),
            server_default="0",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_iiko_sync_runs_tenant_type_started",
        "iiko_sync_runs",
        ["tenant_id", "sync_type", "started_at"],
    )
    op.create_index(
        "ix_iiko_sync_runs_tenant_status_started",
        "iiko_sync_runs",
        ["tenant_id", "status", "started_at"],
    )

    op.create_table(
        "iiko_raw_entities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=48), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=False),
        sa.Column(
            "parent_external_id",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "organization_external_id",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "source_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["iiko_sync_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_type",
            "external_id",
            "payload_hash",
            name="uq_iiko_raw_entity_version",
        ),
    )
    op.create_index(
        "ix_iiko_raw_entities_tenant_entity_external",
        "iiko_raw_entities",
        ["tenant_id", "entity_type", "external_id"],
    )
    op.create_index(
        "ix_iiko_raw_entities_sync_run",
        "iiko_raw_entities",
        ["sync_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_iiko_raw_entities_sync_run",
        table_name="iiko_raw_entities",
    )
    op.drop_index(
        "ix_iiko_raw_entities_tenant_entity_external",
        table_name="iiko_raw_entities",
    )
    op.drop_table("iiko_raw_entities")
    op.drop_index(
        "ix_iiko_sync_runs_tenant_status_started",
        table_name="iiko_sync_runs",
    )
    op.drop_index(
        "ix_iiko_sync_runs_tenant_type_started",
        table_name="iiko_sync_runs",
    )
    op.drop_table("iiko_sync_runs")
