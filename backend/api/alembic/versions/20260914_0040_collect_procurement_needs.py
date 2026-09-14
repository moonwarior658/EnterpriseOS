"""collect procurement needs into purchase requests

Revision ID: 20260914_0040
Revises: 20260914_0039
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_0040"
down_revision: Union[str, Sequence[str], None] = "20260914_0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    legacy_count = connection.execute(sa.text(
        "SELECT count(*) FROM supply_purchase_request_line_sources "
        "WHERE source_type <> 'MANUAL_FUTURE'"
    )).scalar_one()
    if legacy_count:
        raise RuntimeError(
            "Cannot map legacy purchase request sources to procurement needs"
        )

    with op.batch_alter_table("supply_purchase_request_line_sources") as batch:
        batch.add_column(sa.Column("procurement_need_id", sa.Uuid(), nullable=True))
        batch.drop_constraint("ck_supply_purchase_request_line_sources_reference", type_="check")
        batch.drop_constraint("ck_supply_purchase_request_line_sources_type", type_="check")
        batch.create_check_constraint(
            "ck_supply_purchase_request_line_sources_type",
            "source_type IN ('PROCUREMENT_NEED', 'MANUAL_FUTURE')",
        )
        batch.create_check_constraint(
            "ck_supply_purchase_request_line_sources_reference",
            "(source_type = 'MANUAL_FUTURE' AND procurement_need_id IS NULL) OR "
            "(source_type = 'PROCUREMENT_NEED' AND procurement_need_id IS NOT NULL)",
        )
        batch.create_foreign_key(
            "fk_supply_purchase_request_line_sources_need_tenant",
            "supply_procurement_needs", ["tenant_id", "procurement_need_id"],
            ["tenant_id", "id"], ondelete="RESTRICT",
        )
        batch.drop_column("source_id")

    op.create_index(
        "uq_supply_purchase_request_line_sources_need",
        "supply_purchase_request_line_sources", ["tenant_id", "procurement_need_id"],
        unique=True,
        postgresql_where=sa.text("procurement_need_id IS NOT NULL"),
        sqlite_where=sa.text("procurement_need_id IS NOT NULL"),
    )
    with op.batch_alter_table("supply_purchase_request_lines") as batch:
        batch.drop_constraint("ck_supply_purchase_request_lines_manual_future_quantity", type_="check")
        batch.create_check_constraint(
            "ck_supply_purchase_request_lines_manual_future_quantity",
            "manual_future_quantity >= 0",
        )


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM supply_purchase_request_lines "
        "WHERE manual_future_quantity = 0"
    ))
    with op.batch_alter_table("supply_purchase_request_lines") as batch:
        batch.drop_constraint("ck_supply_purchase_request_lines_manual_future_quantity", type_="check")
        batch.create_check_constraint(
            "ck_supply_purchase_request_lines_manual_future_quantity",
            "manual_future_quantity > 0",
        )

    op.drop_index(
        "uq_supply_purchase_request_line_sources_need",
        table_name="supply_purchase_request_line_sources",
    )
    with op.batch_alter_table("supply_purchase_request_line_sources") as batch:
        batch.add_column(sa.Column("source_id", sa.Uuid(), nullable=True))
        batch.drop_constraint(
            "fk_supply_purchase_request_line_sources_need_tenant", type_="foreignkey"
        )
        batch.drop_constraint("ck_supply_purchase_request_line_sources_reference", type_="check")
        batch.drop_constraint("ck_supply_purchase_request_line_sources_type", type_="check")

    connection = op.get_bind()
    connection.execute(sa.text(
        "UPDATE supply_purchase_request_line_sources AS source "
        "SET source_id = source.procurement_need_id, source_type = CASE "
        "WHEN need.source_type = 'REQUEST_LINE' THEN 'SUPPLY_REQUEST' "
        "ELSE 'DEPARTMENT_DEBT' END "
        "FROM supply_procurement_needs AS need "
        "WHERE source.procurement_need_id = need.id "
        "AND source.tenant_id = need.tenant_id"
    ))
    with op.batch_alter_table("supply_purchase_request_line_sources") as batch:
        batch.create_check_constraint(
            "ck_supply_purchase_request_line_sources_type",
            "source_type IN ('SUPPLY_REQUEST', 'DEPARTMENT_DEBT', 'MANUAL_FUTURE')",
        )
        batch.create_check_constraint(
            "ck_supply_purchase_request_line_sources_reference",
            "(source_type = 'MANUAL_FUTURE' AND source_id IS NULL) OR "
            "(source_type <> 'MANUAL_FUTURE' AND source_id IS NOT NULL)",
        )
        batch.drop_column("procurement_need_id")
