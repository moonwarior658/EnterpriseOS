"""add supply roll unit

Revision ID: 20260727_0016
Revises: 20260727_0015
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0016"
down_revision: Union[str, Sequence[str], None] = "20260727_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO supply_units
                (id, tenant_id, code, name_ru, short_name_ru,
                 allows_fraction, is_active)
            VALUES
                ('b20cf0ae-cb8e-4b06-a3ea-a38057a02a06', 'eclair',
                 'ROLL', 'рулон', 'рул', false, true)
            ON CONFLICT (tenant_id, code) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM supply_units
            WHERE tenant_id = 'eclair'
              AND code = 'ROLL'
              AND id = 'b20cf0ae-cb8e-4b06-a3ea-a38057a02a06'
            """
        )
    )
