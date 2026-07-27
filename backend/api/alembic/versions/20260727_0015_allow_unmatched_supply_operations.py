"""allow unmatched supply operations

Revision ID: 20260727_0015
Revises: 20260727_0014
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0015"
down_revision: Union[str, Sequence[str], None] = "20260727_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "supply_department_debts",
        sa.Column("working_name", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE supply_department_debts AS debt
        SET working_name = COALESCE(
            (
                SELECT product.name
                FROM supply_products AS product
                WHERE product.id = debt.product_id
            ),
            (
                SELECT COALESCE(line.parsed_name, line.raw_text)
                FROM supply_request_lines AS line
                WHERE line.id = debt.first_request_line_id
            )
        )
        """
    )
    op.alter_column(
        "supply_department_debts",
        "working_name",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "supply_department_debts",
        "product_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM supply_department_debts
                WHERE product_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade while unmatched supply debts exist';
            END IF;
        END
        $$;
        """
    )
    op.alter_column(
        "supply_department_debts",
        "product_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_column("supply_department_debts", "working_name")
