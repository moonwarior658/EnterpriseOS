"""add supply request planning and approved aliases

Revision ID: 20260727_0013
Revises: 20260727_0012
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0013"
down_revision: Union[str, Sequence[str], None] = "20260727_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_supply_requests_status", "supply_requests", type_="check"
    )
    op.create_check_constraint(
        "ck_supply_requests_status",
        "supply_requests",
        "status IN ('DRAFT', 'SUBMITTED', 'IN_REVIEW', 'PLANNED', "
        "'PARTIALLY_FULFILLED', 'FULFILLED', 'CANCELLED')",
    )
    op.add_column(
        "supply_requests",
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column("planned_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column("cancelled_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "supply_requests",
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_supply_requests_planned_by_user_id_users",
        "supply_requests", "users", ["planned_by_user_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_supply_requests_cancelled_by_user_id_users",
        "supply_requests", "users", ["cancelled_by_user_id"], ["id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "supply_product_aliases",
        sa.Column(
            "status", sa.String(length=24), nullable=False,
            server_default="APPROVED",
        ),
    )
    op.add_column(
        "supply_product_aliases",
        sa.Column(
            "successful_application_count", sa.Integer(), nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "supply_product_aliases",
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "supply_product_aliases",
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_supply_product_aliases_status",
        "supply_product_aliases",
        "status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'DISABLED')",
    )
    op.create_foreign_key(
        "fk_supply_product_aliases_created_by_user_id_users",
        "supply_product_aliases", "users", ["created_by_user_id"], ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "supply_line_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_line_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('TRANSFER', 'PURCHASE', 'CANCEL')",
            name="ck_supply_line_allocations_action",
        ),
        sa.CheckConstraint(
            "planned_quantity > 0",
            name="ck_supply_line_allocations_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["supply_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["request_line_id"], ["supply_request_lines.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["supply_units.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_line_id", "action",
            name="uq_supply_line_allocations_line_action",
        ),
    )
    op.create_index(
        "ix_supply_line_allocations_tenant_request",
        "supply_line_allocations", ["tenant_id", "request_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_line_allocations_tenant_request",
        table_name="supply_line_allocations",
    )
    op.drop_table("supply_line_allocations")
    op.drop_constraint(
        "fk_supply_product_aliases_created_by_user_id_users",
        "supply_product_aliases", type_="foreignkey",
    )
    op.drop_constraint(
        "ck_supply_product_aliases_status",
        "supply_product_aliases", type_="check",
    )
    op.drop_column("supply_product_aliases", "created_by_user_id")
    op.drop_column("supply_product_aliases", "last_applied_at")
    op.drop_column("supply_product_aliases", "successful_application_count")
    op.drop_column("supply_product_aliases", "status")
    op.drop_constraint(
        "fk_supply_requests_cancelled_by_user_id_users",
        "supply_requests", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_supply_requests_planned_by_user_id_users",
        "supply_requests", type_="foreignkey",
    )
    op.drop_column("supply_requests", "cancellation_reason")
    op.drop_column("supply_requests", "cancelled_by_user_id")
    op.drop_column("supply_requests", "cancelled_at")
    op.drop_column("supply_requests", "planned_by_user_id")
    op.drop_column("supply_requests", "planned_at")
    op.drop_constraint(
        "ck_supply_requests_status", "supply_requests", type_="check"
    )
    op.create_check_constraint(
        "ck_supply_requests_status",
        "supply_requests",
        "status IN ('DRAFT', 'SUBMITTED', 'CANCELLED')",
    )
