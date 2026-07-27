"""add supply request line recognition and matching

Revision ID: 20260727_0009
Revises: 20260727_0008
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0009"
down_revision: Union[str, Sequence[str], None] = "20260727_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "supply_request_lines",
        sa.Column("parsed_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("parsed_quantity", sa.Numeric(18, 3), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("parsed_unit_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column(
            "match_status",
            sa.String(length=24),
            server_default=sa.text("'UNPROCESSED'"),
            nullable=False,
        ),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("match_method", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("matched_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("match_notes", sa.Text(), nullable=True),
    )

    op.create_foreign_key(
        "fk_supply_request_lines_parsed_unit_id",
        "supply_request_lines",
        "supply_units",
        ["parsed_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_supply_request_lines_matched_by_user_id",
        "supply_request_lines",
        "users",
        ["matched_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_supply_request_lines_match_status",
        "supply_request_lines",
        "match_status IN ('UNPROCESSED', 'PARSED', 'MATCHED', "
        "'NEEDS_REVIEW', 'REJECTED')",
    )
    op.create_check_constraint(
        "ck_supply_request_lines_match_method",
        "supply_request_lines",
        "match_method IS NULL OR match_method IN "
        "('EXACT_PRODUCT', 'EXACT_ALIAS', 'MANUAL')",
    )
    op.create_check_constraint(
        "ck_supply_request_lines_parsed_quantity_positive",
        "supply_request_lines",
        "parsed_quantity IS NULL OR parsed_quantity > 0",
    )
    op.create_check_constraint(
        "ck_supply_request_lines_match_confidence",
        "supply_request_lines",
        "match_confidence IS NULL OR "
        "(match_confidence >= 0 AND match_confidence <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_supply_request_lines_match_confidence",
        "supply_request_lines",
        type_="check",
    )
    op.drop_constraint(
        "ck_supply_request_lines_parsed_quantity_positive",
        "supply_request_lines",
        type_="check",
    )
    op.drop_constraint(
        "ck_supply_request_lines_match_method",
        "supply_request_lines",
        type_="check",
    )
    op.drop_constraint(
        "ck_supply_request_lines_match_status",
        "supply_request_lines",
        type_="check",
    )
    op.drop_constraint(
        "fk_supply_request_lines_matched_by_user_id",
        "supply_request_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_supply_request_lines_parsed_unit_id",
        "supply_request_lines",
        type_="foreignkey",
    )
    op.drop_column("supply_request_lines", "match_notes")
    op.drop_column("supply_request_lines", "match_confidence")
    op.drop_column("supply_request_lines", "matched_by_user_id")
    op.drop_column("supply_request_lines", "matched_at")
    op.drop_column("supply_request_lines", "match_method")
    op.drop_column("supply_request_lines", "match_status")
    op.drop_column("supply_request_lines", "parsed_unit_id")
    op.drop_column("supply_request_lines", "parsed_quantity")
    op.drop_column("supply_request_lines", "parsed_name")
