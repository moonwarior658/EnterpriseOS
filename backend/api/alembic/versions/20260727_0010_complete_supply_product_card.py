"""complete supply product card

Revision ID: 20260727_0010
Revises: 20260727_0009
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_0010"
down_revision: Union[str, Sequence[str], None] = "20260727_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_reference_table(
    table_name: str,
    *,
    code_constraint: str,
    name_constraint: str,
    active_index: str,
) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("normalized_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
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
        sa.UniqueConstraint("tenant_id", "code", name=code_constraint),
        sa.UniqueConstraint(
            "tenant_id",
            "normalized_name",
            name=name_constraint,
        ),
    )
    op.create_index(
        active_index,
        table_name,
        ["tenant_id", "is_active", "sort_order"],
        unique=False,
    )


def upgrade() -> None:
    _create_reference_table(
        "supply_product_categories",
        code_constraint="uq_supply_product_categories_tenant_code",
        name_constraint="uq_supply_product_categories_tenant_normalized_name",
        active_index="ix_supply_product_categories_tenant_active_order",
    )
    _create_reference_table(
        "supply_storage_zones",
        code_constraint="uq_supply_storage_zones_tenant_code",
        name_constraint="uq_supply_storage_zones_tenant_normalized_name",
        active_index="ix_supply_storage_zones_tenant_active_order",
    )

    op.add_column(
        "supply_products",
        sa.Column("iiko_id", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "supply_products",
        sa.Column("category_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "supply_products",
        sa.Column("storage_zone_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "supply_products",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "supply_products",
        sa.Column("archived_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_supply_products_category_id",
        "supply_products",
        "supply_product_categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_supply_products_storage_zone_id",
        "supply_products",
        "supply_storage_zones",
        ["storage_zone_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_supply_products_archived_by_user_id",
        "supply_products",
        "users",
        ["archived_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        sa.text(
            """
            UPDATE supply_products
            SET is_active = true,
                archived_at = NULL,
                archived_by_user_id = NULL
            """
        )
    )
    op.create_check_constraint(
        "ck_supply_products_archive_state",
        "supply_products",
        "(is_active = true AND archived_at IS NULL AND "
        "archived_by_user_id IS NULL) OR "
        "(is_active = false AND archived_at IS NOT NULL AND "
        "archived_by_user_id IS NOT NULL)",
    )
    op.create_index(
        "uq_supply_products_tenant_iiko_id",
        "supply_products",
        ["tenant_id", "iiko_id"],
        unique=True,
        postgresql_where=sa.text("iiko_id IS NOT NULL"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO supply_storage_zones
                (id, tenant_id, code, name, normalized_name, sort_order)
            VALUES
                ('c70d83d4-50db-4ee1-9382-c837af400101', 'eclair',
                 'FREEZER', 'Морозильник', 'морозильник', 10),
                ('c70d83d4-50db-4ee1-9382-c837af400102', 'eclair',
                 'REFRIGERATOR', 'Холодильник', 'холодильник', 20),
                ('c70d83d4-50db-4ee1-9382-c837af400103', 'eclair',
                 'DRY_STORAGE', 'Сухой склад', 'сухой склад', 30),
                ('c70d83d4-50db-4ee1-9382-c837af400104', 'eclair',
                 'PACKAGING_STORAGE', 'Склад упаковки',
                 'склад упаковки', 40),
                ('c70d83d4-50db-4ee1-9382-c837af400105', 'eclair',
                 'HOUSEHOLD_STORAGE', 'Хозсклад', 'хозсклад', 50),
                ('c70d83d4-50db-4ee1-9382-c837af400106', 'eclair',
                 'FIXED_ASSETS', 'Основные средства',
                 'основные средства', 60),
                ('c70d83d4-50db-4ee1-9382-c837af400107', 'eclair',
                 'OTHER', 'Другое', 'другое', 70)
            ON CONFLICT (tenant_id, code) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "uq_supply_products_tenant_iiko_id",
        table_name="supply_products",
    )
    op.drop_constraint(
        "ck_supply_products_archive_state",
        "supply_products",
        type_="check",
    )
    op.drop_constraint(
        "fk_supply_products_archived_by_user_id",
        "supply_products",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_supply_products_storage_zone_id",
        "supply_products",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_supply_products_category_id",
        "supply_products",
        type_="foreignkey",
    )
    op.drop_column("supply_products", "archived_by_user_id")
    op.drop_column("supply_products", "archived_at")
    op.drop_column("supply_products", "storage_zone_id")
    op.drop_column("supply_products", "category_id")
    op.drop_column("supply_products", "iiko_id")

    op.drop_index(
        "ix_supply_storage_zones_tenant_active_order",
        table_name="supply_storage_zones",
    )
    op.drop_table("supply_storage_zones")
    op.drop_index(
        "ix_supply_product_categories_tenant_active_order",
        table_name="supply_product_categories",
    )
    op.drop_table("supply_product_categories")
