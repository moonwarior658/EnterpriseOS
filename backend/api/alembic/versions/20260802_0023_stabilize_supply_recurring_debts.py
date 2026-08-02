"""preserve unit-specific supply recurring debts

Revision ID: 20260802_0023
Revises: 20260802_0022
Create Date: 2026-08-02
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260802_0023"
down_revision: Union[str, Sequence[str], None] = "20260802_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
