"""expand work requests with public authors, attachments and comments

Revision ID: 20260726_0006
Revises: 20260726_0005
Create Date: 2026-07-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_0006"
down_revision: Union[str, Sequence[str], None] = "20260726_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_AND_CURRENT_DEPARTMENTS = (
    "department IN ("
    "'М15', 'М35', 'М6А', 'Цех ГХ', 'Бар ГХ', 'Кухня', 'Авто', "
    "'Производство', 'Кондитерский цех', 'Кафе', 'М6а', "
    "'Снабжение', 'Администрация', 'Другое'"
    ")"
)

LEGACY_DEPARTMENTS = (
    "department IN ("
    "'Производство', 'Кондитерский цех', 'Кафе', 'М15', 'М6а', "
    "'М35', 'Снабжение', 'Администрация', 'Другое'"
    ")"
)


def upgrade() -> None:
    op.alter_column(
        "work_requests",
        "created_by_user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        "work_requests",
        sa.Column("author_name", sa.String(length=128), nullable=True),
    )
    op.drop_constraint(
        "ck_work_requests_department",
        "work_requests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_work_requests_department",
        "work_requests",
        LEGACY_AND_CURRENT_DEPARTMENTS,
    )

    op.create_table(
        "work_request_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_request_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["work_request_id"],
            ["work_requests.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename"),
    )
    op.create_index(
        op.f("ix_work_request_attachments_work_request_id"),
        "work_request_attachments",
        ["work_request_id"],
        unique=False,
    )

    op.create_table(
        "work_request_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_request_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(body)) > 0 AND length(body) <= 2000",
            name="ck_work_request_comments_body",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_request_id"],
            ["work_requests.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_work_request_comments_author_user_id"),
        "work_request_comments",
        ["author_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_request_comments_work_request_id"),
        "work_request_comments",
        ["work_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_work_request_comments_work_request_id"),
        table_name="work_request_comments",
    )
    op.drop_index(
        op.f("ix_work_request_comments_author_user_id"),
        table_name="work_request_comments",
    )
    op.drop_table("work_request_comments")
    op.drop_index(
        op.f("ix_work_request_attachments_work_request_id"),
        table_name="work_request_attachments",
    )
    op.drop_table("work_request_attachments")

    op.execute(
        sa.text(
            "DELETE FROM work_requests "
            "WHERE created_by_user_id IS NULL "
            "OR department NOT IN ("
            "'Производство', 'Кондитерский цех', 'Кафе', 'М15', 'М6а', "
            "'М35', 'Снабжение', 'Администрация', 'Другое'"
            ")"
        )
    )
    op.drop_constraint(
        "ck_work_requests_department",
        "work_requests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_work_requests_department",
        "work_requests",
        LEGACY_DEPARTMENTS,
    )
    op.drop_column("work_requests", "author_name")
    op.alter_column(
        "work_requests",
        "created_by_user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
