"""add tenant-scoped read-only request access

Revision ID: 20260806_0029
Revises: 20260805_0028
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0029"
down_revision: Union[str, Sequence[str], None] = "20260805_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRODUCTION_TENANT_ID = "eclair"


def _assert_single_tenant_production() -> None:
    """0029 intentionally targets the current single-tenant production."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    preparer = bind.dialect.identifier_preparer
    conflicting_tables: list[str] = []

    for table_name in sorted(inspector.get_table_names()):
        if table_name == "alembic_version":
            continue
        columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        if "tenant_id" not in columns:
            continue
        quoted_table = preparer.quote(table_name)
        conflict = bind.scalar(sa.text(
            f"SELECT 1 FROM {quoted_table} "
            "WHERE tenant_id IS NULL OR tenant_id != :tenant_id LIMIT 1"
        ), {"tenant_id": PRODUCTION_TENANT_ID})
        if conflict is not None:
            conflicting_tables.append(table_name)

    if conflicting_tables:
        raise RuntimeError(
            "Migration 0029 supports only tenant 'eclair'; "
            "conflicting tenant data found in: "
            + ", ".join(conflicting_tables)
        )


def upgrade() -> None:
    # Current production is intentionally single-tenant. Stop atomically
    # before the eclair backfill if any existing tenant-bearing table proves
    # otherwise.
    _assert_single_tenant_production()

    op.add_column(
        "users",
        sa.Column(
            "can_view_requests",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            server_default="eclair",
            nullable=False,
        ),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.alter_column("users", "tenant_id", server_default=None)

    op.add_column(
        "work_requests",
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            server_default="eclair",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_work_requests_tenant_id", "work_requests", ["tenant_id"]
    )
    op.alter_column("work_requests", "tenant_id", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_work_requests_tenant_id", table_name="work_requests")
    op.drop_column("work_requests", "tenant_id")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_column("users", "tenant_id")
    op.drop_column("users", "can_view_requests")
