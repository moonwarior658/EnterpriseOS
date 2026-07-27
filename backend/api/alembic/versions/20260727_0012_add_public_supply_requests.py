"""add public supply request access metadata

Revision ID: 20260727_0012
Revises: 20260727_0011
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0012"
down_revision: Union[str, Sequence[str], None] = "20260727_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "supply_requests",
        sa.Column("public_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column(
            "public_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "supply_requests",
        sa.Column("public_author_name", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column("public_author_phone", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column("source_ip_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column(
            "public_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_supply_requests_public_token_hash",
        "supply_requests",
        ["public_token_hash"],
        unique=True,
        postgresql_where=sa.text("public_token_hash IS NOT NULL"),
    )
    op.create_index(
        "ix_supply_requests_source_ip_created",
        "supply_requests",
        ["source_ip_hash", "public_created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_requests_source_ip_created",
        table_name="supply_requests",
    )
    op.drop_index(
        "uq_supply_requests_public_token_hash",
        table_name="supply_requests",
    )
    op.drop_column("supply_requests", "public_created_at")
    op.drop_column("supply_requests", "source_ip_hash")
    op.drop_column("supply_requests", "public_author_phone")
    op.drop_column("supply_requests", "public_author_name")
    op.drop_column("supply_requests", "public_token_expires_at")
    op.drop_column("supply_requests", "public_token_hash")
