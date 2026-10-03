"""Add contractor pricing terms.

Revision ID: 20261002_0066
Revises: 20261001_0065
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261002_0066"
down_revision: str | None = "20261001_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("external_contractors", sa.Column("price_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("external_contractors", "price_notes")
