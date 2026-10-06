"""Preserve confirmed Seller payload separately from pending edits.

Revision ID: 20261006_0069
Revises: 20261002_0068
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261006_0069"
down_revision: str | None = "20261002_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("supply_requests", sa.Column("seller_draft_input", sa.Text(), nullable=True))
    op.add_column("supply_requests", sa.Column("seller_confirmed_snapshot", sa.JSON(none_as_null=True), nullable=True))
    op.add_column("supply_requests", sa.Column("seller_finalized_at", sa.DateTime(timezone=True), nullable=True))
    # Only known, currently confirmed Seller requests in open windows are adopted.
    # Previously overwritten DRAFT data cannot be inferred from today's rows.
    op.execute("""
        UPDATE supply_requests r SET seller_confirmed_snapshot = json_build_object(
            'version', r.version, 'raw_input', r.raw_input, 'submitted_at', r.submitted_at,
            'lines', COALESCE((SELECT json_agg(json_build_object(
                'id', l.id, 'position', l.position, 'raw_text', l.raw_text
            ) ORDER BY l.position) FROM supply_request_lines l
                WHERE l.request_id = r.id AND l.tenant_id = r.tenant_id), '[]'::json)
        )
        FROM supply_request_cycles c
        WHERE r.cycle_id = c.id AND r.tenant_id = c.tenant_id
          AND c.status = 'OPEN' AND r.status = 'SUBMITTED'
          AND r.creator_authorized_as = 'SELLER' AND r.submitted_at IS NOT NULL
    """)
    op.create_check_constraint("ck_supply_requests_seller_draft_confirmed", "supply_requests",
                               "seller_draft_input IS NULL OR seller_confirmed_snapshot IS NOT NULL")
    op.create_check_constraint("ck_supply_requests_seller_finalized_confirmed", "supply_requests",
                               "seller_finalized_at IS NULL OR seller_confirmed_snapshot IS NOT NULL")


def downgrade() -> None:
    # Never turn an abandoned edit into the business payload during rollback.
    # Pending draft edits/snapshots are removed; confirmed rows remain authoritative.
    op.drop_constraint("ck_supply_requests_seller_finalized_confirmed", "supply_requests", type_="check")
    op.drop_constraint("ck_supply_requests_seller_draft_confirmed", "supply_requests", type_="check")
    op.drop_column("supply_requests", "seller_finalized_at")
    op.drop_column("supply_requests", "seller_confirmed_snapshot")
    op.drop_column("supply_requests", "seller_draft_input")
