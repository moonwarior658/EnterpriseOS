"""add supply product catalog and units

Revision ID: 20260727_0008
Revises: 20260727_0007
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0008"
down_revision: Union[str, Sequence[str], None] = "20260727_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name_ru", sa.String(length=120), nullable=False),
        sa.Column("short_name_ru", sa.String(length=32), nullable=False),
        sa.Column(
            "allows_fraction",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
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
            name="uq_supply_units_tenant_code",
        ),
    )
    op.create_index(
        "ix_supply_units_tenant_active_code",
        "supply_units",
        ["tenant_id", "is_active", "code"],
        unique=False,
    )

    op.create_table(
        "supply_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("normalized_name", sa.String(length=240), nullable=False),
        sa.Column("default_unit_id", sa.Uuid(), nullable=False),
        sa.Column("request_direction_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
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
        sa.ForeignKeyConstraint(
            ["default_unit_id"],
            ["supply_units.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_direction_id"],
            ["supply_request_directions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "normalized_name",
            name="uq_supply_products_tenant_normalized_name",
        ),
    )
    op.create_index(
        "ix_supply_products_tenant_active_name",
        "supply_products",
        ["tenant_id", "is_active", "normalized_name"],
        unique=False,
    )

    op.create_table(
        "supply_product_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=240), nullable=False),
        sa.Column("normalized_alias", sa.String(length=240), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["supply_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "normalized_alias",
            name="uq_supply_product_aliases_tenant_normalized_alias",
        ),
    )
    op.create_index(
        "ix_supply_product_aliases_product",
        "supply_product_aliases",
        ["product_id", "created_at"],
        unique=False,
    )

    op.add_column(
        "supply_request_lines",
        sa.Column("product_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("requested_unit_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "supply_request_lines",
        sa.Column("quantity", sa.Numeric(18, 3), nullable=True),
    )
    op.create_check_constraint(
        "ck_supply_request_lines_quantity_positive",
        "supply_request_lines",
        "quantity IS NULL OR quantity > 0",
    )
    op.create_foreign_key(
        "fk_supply_request_lines_product_id",
        "supply_request_lines",
        "supply_products",
        ["product_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_supply_request_lines_requested_unit_id",
        "supply_request_lines",
        "supply_units",
        ["requested_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        sa.text(
            """
            INSERT INTO supply_units
                (id, tenant_id, code, name_ru, short_name_ru,
                 allows_fraction, is_active)
            VALUES
                ('b20cf0ae-cb8e-4b06-a3ea-a38057a02a01', 'eclair',
                 'KG', 'килограмм', 'кг', true, true),
                ('b20cf0ae-cb8e-4b06-a3ea-a38057a02a02', 'eclair',
                 'L', 'литр', 'л', true, true),
                ('b20cf0ae-cb8e-4b06-a3ea-a38057a02a03', 'eclair',
                 'PCS', 'штука', 'шт', false, true),
                ('b20cf0ae-cb8e-4b06-a3ea-a38057a02a04', 'eclair',
                 'PACK', 'упаковка', 'уп', false, true),
                ('b20cf0ae-cb8e-4b06-a3ea-a38057a02a05', 'eclair',
                 'BOX', 'коробка', 'кор', false, true)
            ON CONFLICT (tenant_id, code) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_supply_request_lines_requested_unit_id",
        "supply_request_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_supply_request_lines_product_id",
        "supply_request_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_supply_request_lines_quantity_positive",
        "supply_request_lines",
        type_="check",
    )
    op.drop_column("supply_request_lines", "quantity")
    op.drop_column("supply_request_lines", "requested_unit_id")
    op.drop_column("supply_request_lines", "product_id")

    op.drop_index(
        "ix_supply_product_aliases_product",
        table_name="supply_product_aliases",
    )
    op.drop_table("supply_product_aliases")
    op.drop_index(
        "ix_supply_products_tenant_active_name",
        table_name="supply_products",
    )
    op.drop_table("supply_products")
    op.drop_index(
        "ix_supply_units_tenant_active_code",
        table_name="supply_units",
    )
    op.drop_table("supply_units")
