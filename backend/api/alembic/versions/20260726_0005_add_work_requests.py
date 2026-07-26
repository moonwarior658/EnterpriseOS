"""add department work requests

Revision ID: 20260726_0005
Revises: 20260722_0004
Create Date: 2026-07-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_0005"
down_revision: Union[str, Sequence[str], None] = "20260722_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_type", sa.String(length=16), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="new",
            nullable=False,
        ),
        sa.Column("warehouse_category", sa.String(length=16), nullable=True),
        sa.Column("repair_category", sa.String(length=64), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
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
            "request_type IN ('warehouse', 'repair')",
            name="ck_work_requests_type",
        ),
        sa.CheckConstraint(
            "department IN ("
            "'Производство', 'Кондитерский цех', 'Кафе', 'М15', 'М6а', "
            "'М35', 'Снабжение', 'Администрация', 'Другое'"
            ")",
            name="ck_work_requests_department",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'completed', 'cancelled')",
            name="ck_work_requests_status",
        ),
        sa.CheckConstraint(
            "length(trim(description)) > 0 AND length(description) <= 5000",
            name="ck_work_requests_description",
        ),
        sa.CheckConstraint(
            "("
            "request_type = 'warehouse' "
            "AND warehouse_category IN ('products', 'household', 'packaging') "
            "AND repair_category IS NULL AND priority IS NULL"
            ") OR ("
            "request_type = 'repair' "
            "AND warehouse_category IS NULL "
            "AND repair_category IN ("
            "'Сантехника', 'Электрика', 'Кассовое оборудование', "
            "'Компьютерное оборудование', 'Холодильное оборудование', "
            "'Тепловое оборудование', 'Кофемашина', 'Интернет', 'Другое'"
            ") "
            "AND priority IN ('routine', 'important', 'urgent')"
            ")",
            name="ck_work_requests_type_fields",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_work_requests_created_at"),
        "work_requests",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_requests_created_by_user_id"),
        "work_requests",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_work_requests_created_by_user_id"),
        table_name="work_requests",
    )
    op.drop_index(
        op.f("ix_work_requests_created_at"),
        table_name="work_requests",
    )
    op.drop_table("work_requests")
