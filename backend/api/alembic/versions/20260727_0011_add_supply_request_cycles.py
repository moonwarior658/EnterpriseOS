"""add supply request cycles, uniqueness and duplicate metadata

Revision ID: 20260727_0011
Revises: 20260727_0010
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0011"
down_revision: Union[str, Sequence[str], None] = "20260727_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_request_cycles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("direction_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_date", sa.Date(), nullable=False),
        sa.Column(
            "opens_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "closes_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "hard_closes_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'SCHEDULED'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'OPEN', 'CLOSED', 'CANCELLED')",
            name="ck_supply_request_cycles_status",
        ),
        sa.CheckConstraint(
            "closes_at > opens_at",
            name="ck_supply_request_cycles_time_window",
        ),
        sa.CheckConstraint(
            "hard_closes_at IS NULL OR hard_closes_at >= closes_at",
            name="ck_supply_request_cycles_hard_close",
        ),
        sa.ForeignKeyConstraint(
            ["direction_id"],
            ["supply_request_directions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "direction_id",
            "cycle_date",
            name="uq_supply_request_cycles_tenant_direction_date",
        ),
    )
    op.create_index(
        "ix_supply_request_cycles_tenant_date_status",
        "supply_request_cycles",
        ["tenant_id", "cycle_date", "status"],
        unique=False,
    )

    op.add_column(
        "supply_requests",
        sa.Column("cycle_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_supply_requests_cycle_id",
        "supply_requests",
        "supply_request_cycles",
        ["cycle_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_supply_requests_tenant_department_direction_cycle",
        "supply_requests",
        ["tenant_id", "department_id", "direction_id", "cycle_id"],
    )

    op.add_column(
        "supply_request_lines",
        sa.Column("duplicate_group_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column(
            "duplicate_status",
            sa.String(length=24),
            server_default=sa.text("'NONE'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_supply_request_lines_duplicate_status",
        "supply_request_lines",
        "duplicate_status IN ('NONE', 'SUSPECTED', 'CONFIRMED', 'RESOLVED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_supply_request_lines_duplicate_status",
        "supply_request_lines",
        type_="check",
    )
    op.drop_column("supply_request_lines", "duplicate_status")
    op.drop_column("supply_request_lines", "duplicate_group_id")

    op.drop_constraint(
        "uq_supply_requests_tenant_department_direction_cycle",
        "supply_requests",
        type_="unique",
    )
    op.drop_constraint(
        "fk_supply_requests_cycle_id",
        "supply_requests",
        type_="foreignkey",
    )
    op.drop_column("supply_requests", "cycle_id")

    op.drop_index(
        "ix_supply_request_cycles_tenant_date_status",
        table_name="supply_request_cycles",
    )
    op.drop_table("supply_request_cycles")
