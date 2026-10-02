"""Attach a payment photo to a supplier payment.

Revision ID: 20261002_0068
Revises: 20261002_0067
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20261002_0068"
down_revision: str | None = "20261002_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("supply_supplier_payments", sa.Column("photo_filename", sa.String(80), nullable=True))
    op.add_column("supply_supplier_payments", sa.Column("photo_original_name", sa.String(255), nullable=True))
    op.add_column("supply_supplier_payments", sa.Column("photo_content_type", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("supply_supplier_payments", "photo_content_type")
    op.drop_column("supply_supplier_payments", "photo_original_name")
    op.drop_column("supply_supplier_payments", "photo_filename")
