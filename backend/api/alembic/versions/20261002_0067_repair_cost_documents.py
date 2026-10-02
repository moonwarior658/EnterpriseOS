"""Repair cost and external documents.

Revision ID: 20261002_0067
Revises: 20261002_0066
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20261002_0067"
down_revision: str | None = "20261002_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column("work_requests", sa.Column("repair_cost", sa.Numeric(14, 2), nullable=True))
    op.create_check_constraint("ck_work_requests_repair_cost_positive", "work_requests", "repair_cost IS NULL OR repair_cost > 0")
    op.add_column("work_request_attachments", sa.Column("kind", sa.String(16), server_default="PHOTO", nullable=False))
    op.create_check_constraint("ck_work_request_attachments_kind", "work_request_attachments", "kind IN ('PHOTO', 'INVOICE', 'ACT')")

def downgrade() -> None:
    op.drop_constraint("ck_work_request_attachments_kind", "work_request_attachments", type_="check")
    op.drop_column("work_request_attachments", "kind")
    op.drop_constraint("ck_work_requests_repair_cost_positive", "work_requests", type_="check")
    op.drop_column("work_requests", "repair_cost")
