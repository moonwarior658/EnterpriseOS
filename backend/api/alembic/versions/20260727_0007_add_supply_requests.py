"""add supply request foundation

Revision ID: 20260727_0007
Revises: 20260726_0006
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0007"
down_revision: Union[str, Sequence[str], None] = "20260726_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            server_default="0",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_departments_tenant_code",
        ),
    )
    op.create_index(
        "ix_departments_tenant_active_order",
        "departments",
        ["tenant_id", "is_active", "display_order"],
        unique=False,
    )

    op.create_table(
        "supply_request_directions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            server_default="0",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_supply_request_directions_tenant_code",
        ),
    )
    op.create_index(
        "ix_supply_request_directions_tenant_active_order",
        "supply_request_directions",
        ["tenant_id", "is_active", "display_order"],
        unique=False,
    )

    op.create_table(
        "supply_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("public_number", sa.String(length=160), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("direction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column(
            "source_type",
            sa.String(length=32),
            server_default="INTERNAL",
            nullable=False,
        ),
        sa.Column("source_work_request_id", sa.Integer(), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
            "status IN ('DRAFT', 'SUBMITTED', 'CANCELLED')",
            name="ck_supply_requests_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('INTERNAL', 'PUBLIC_FORM', "
            "'WORK_REQUEST_MANUAL')",
            name="ck_supply_requests_source_type",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_supply_requests_version",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["direction_id"],
            ["supply_request_directions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_work_request_id"],
            ["work_requests.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "public_number",
            name="uq_supply_requests_tenant_public_number",
        ),
    )
    op.create_index(
        "ix_supply_requests_tenant_created",
        "supply_requests",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "supply_request_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
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
            "position >= 1",
            name="ck_supply_request_lines_position",
        ),
        sa.CheckConstraint(
            "length(trim(raw_text)) > 0",
            name="ck_supply_request_lines_raw_text",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["supply_requests.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            "position",
            name="uq_supply_request_lines_request_position",
        ),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO departments
                (id, tenant_id, code, name, is_active, display_order)
            VALUES
                ('a29ac646-322f-47ab-8d31-d3d41fe1a510', 'eclair',
                 'М15', 'Матросова 15', true, 10),
                ('246a46d1-6ad8-4894-a039-d3756b10b4b2', 'eclair',
                 'М35', 'Матросова 35', true, 20),
                ('8a1f09e8-8948-40e8-bdaf-b04f94375be8', 'eclair',
                 'М6А', 'Маяковского 6а', true, 30),
                ('4ec6b282-b1c3-450a-8bfb-5f35c946f1ce', 'eclair',
                 'ЦЕХ', 'Цех производство', true, 40),
                ('9c4b181c-ac05-4a03-bf5a-3a6bf10d2d09', 'eclair',
                 'ATO', 'Авто', true, 50)
            ON CONFLICT (tenant_id, code) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO supply_request_directions
                (id, tenant_id, code, name, is_active, display_order)
            VALUES
                ('377f8383-f21d-474a-bdf9-4d08edac669b', 'eclair',
                 'MAIN', 'Основной', true, 10),
                ('3b10f49d-9e7c-4a36-8551-cc9e2e179f2a', 'eclair',
                 'HOUSEHOLD', 'Хозяйственный', true, 20)
            ON CONFLICT (tenant_id, code) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("supply_request_lines")
    op.drop_index(
        "ix_supply_requests_tenant_created",
        table_name="supply_requests",
    )
    op.drop_table("supply_requests")
    op.drop_index(
        "ix_supply_request_directions_tenant_active_order",
        table_name="supply_request_directions",
    )
    op.drop_table("supply_request_directions")
    op.drop_index(
        "ix_departments_tenant_active_order",
        table_name="departments",
    )
    op.drop_table("departments")
