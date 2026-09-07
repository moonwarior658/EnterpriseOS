"""add supply suppliers

Revision ID: 20260907_0035
Revises: 20260824_0034
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260907_0035"
down_revision: Union[str, Sequence[str], None] = "20260824_0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("legal_name", sa.String(length=240), nullable=True),
        sa.Column("inn", sa.String(length=32), nullable=True),
        sa.Column("kpp", sa.String(length=32), nullable=True),
        sa.Column("ogrn", sa.String(length=32), nullable=True),
        sa.Column("legal_address", sa.String(length=1000), nullable=True),
        sa.Column("actual_address", sa.String(length=1000), nullable=True),
        sa.Column("bank_name", sa.String(length=240), nullable=True),
        sa.Column("bik", sa.String(length=32), nullable=True),
        sa.Column(
            "correspondent_account", sa.String(length=64), nullable=True
        ),
        sa.Column("settlement_account", sa.String(length=64), nullable=True),
        sa.Column("order_email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "archived_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("archived_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(is_active = true AND archived_at IS NULL AND "
            "archived_by_user_id IS NULL) OR "
            "(is_active = false AND archived_at IS NOT NULL AND "
            "archived_by_user_id IS NOT NULL)",
            name="ck_supply_suppliers_archive_state",
        ),
        sa.ForeignKeyConstraint(
            ["archived_by_user_id"],
            ["users.id"],
            name="fk_supply_suppliers_archived_by_user_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_supply_suppliers_tenant_id"
        ),
    )
    op.create_index(
        "ix_supply_suppliers_tenant_active_name",
        "supply_suppliers",
        ["tenant_id", "is_active", "display_name"],
        unique=False,
    )
    op.create_index(
        "uq_supply_suppliers_tenant_active_inn",
        "supply_suppliers",
        ["tenant_id", "inn"],
        unique=True,
        postgresql_where=sa.text("inn IS NOT NULL AND is_active = true"),
        sqlite_where=sa.text("inn IS NOT NULL AND is_active = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_supply_suppliers_tenant_active_inn",
        table_name="supply_suppliers",
    )
    op.drop_index(
        "ix_supply_suppliers_tenant_active_name",
        table_name="supply_suppliers",
    )
    op.drop_table("supply_suppliers")
