"""add normalized expected payload to iiko document intents

Revision ID: 20260811_0031
Revises: 20260811_0030
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260811_0031"
down_revision: Union[str, Sequence[str], None] = "20260811_0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "iiko_document_writes",
        sa.Column(
            "expected_payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("iiko_document_writes", "expected_payload")
