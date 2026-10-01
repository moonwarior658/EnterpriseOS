"""Classify current departments for RBAC without changing historical facts.

Revision ID: 20261001_0063
Revises: 20260929_0062
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261001_0063"
down_revision: str | None = "20260929_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("departments", sa.Column("business_type", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_departments_business_type", "departments",
        "business_type IN ('RETAIL_POINT', 'PRODUCTION', 'AUTO')",
    )
    connection = op.get_bind()
    for code, name, category in (
        ("М15", "Матросова 15", "RETAIL_POINT"),
        ("М35", "Матросова 35", "RETAIL_POINT"),
        ("ЦЕХ", "Цех производство", "PRODUCTION"),
        ("ATO", "Авто", "AUTO"),
    ):
        connection.execute(sa.text(
            "UPDATE departments SET business_type = :category "
            "WHERE tenant_id = 'eclair' AND code = :code AND name = :name "
            "AND business_type IS NULL"
        ), {"code": code, "name": name, "category": category})
    # A conflicting current И25 is left for the pre-rollout inventory to resolve.
    connection.execute(sa.text(
        "UPDATE departments SET code = 'И25', name = 'Игарская 25В', "
        "business_type = 'RETAIL_POINT' "
        "WHERE tenant_id = 'eclair' AND code = 'М6А' AND name = 'Маяковского 6а' "
        "AND NOT EXISTS (SELECT 1 FROM departments AS existing "
        "WHERE existing.tenant_id = 'eclair' AND existing.code = 'И25')"
    ))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text(
        "UPDATE departments SET code = 'М6А', name = 'Маяковского 6а' "
        "WHERE tenant_id = 'eclair' AND code = 'И25' AND name = 'Игарская 25В' "
        "AND NOT EXISTS (SELECT 1 FROM departments AS existing "
        "WHERE existing.tenant_id = 'eclair' AND existing.code = 'М6А')"
    ))
    op.drop_constraint("ck_departments_business_type", "departments", type_="check")
    op.drop_column("departments", "business_type")
