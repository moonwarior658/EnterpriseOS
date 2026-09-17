"""add acceptance shortage and excess resolutions

Revision ID: 20260917_0051
Revises: 20260917_0050
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260917_0051"
down_revision: str | None = "20260917_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_supply_supplier_acceptance_lines_tenant_id_acceptance",
        "supply_supplier_acceptance_lines", ["tenant_id", "id", "acceptance_id"],
    )
    op.create_table(
        "supply_acceptance_resolutions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("supplier_acceptance_id", sa.Uuid(), nullable=False),
        sa.Column("acceptance_line_id", sa.Uuid(), nullable=False),
        sa.Column("issue_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="OPEN", nullable=False),
        sa.Column("resolution_type", sa.String(32), nullable=True),
        sa.Column("quantity", sa.Numeric(30, 6), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_acceptance_resolutions_tenant_id"),
        sa.UniqueConstraint("tenant_id", "acceptance_line_id", "issue_type", name="uq_supply_acceptance_resolutions_line_issue"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_acceptance_id"], ["supply_supplier_acceptances.tenant_id", "supply_supplier_acceptances.id"], name="fk_supply_acceptance_resolutions_acceptance_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "acceptance_line_id", "supplier_acceptance_id"], ["supply_supplier_acceptance_lines.tenant_id", "supply_supplier_acceptance_lines.id", "supply_supplier_acceptance_lines.acceptance_id"], name="fk_supply_acceptance_resolutions_line_acceptance_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "unit_id"], ["supply_units.tenant_id", "supply_units.id"], name="fk_supply_acceptance_resolutions_unit_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("issue_type IN ('SHORTAGE','EXCESS','REJECTED')", name="ck_supply_acceptance_resolutions_issue_type"),
        sa.CheckConstraint("status IN ('OPEN','RESOLVED','CANCELLED')", name="ck_supply_acceptance_resolutions_status"),
        sa.CheckConstraint("quantity > 0", name="ck_supply_acceptance_resolutions_quantity"),
        sa.CheckConstraint(
            "resolution_type IS NULL OR "
            "(issue_type = 'SHORTAGE' AND resolution_type IN ('WAIT_FOR_DELIVERY','CLOSE_SHORTAGE','RETURN_TO_PROCUREMENT')) OR "
            "(issue_type = 'REJECTED' AND resolution_type IN ('WAIT_FOR_REPLACEMENT','CLOSE_REJECTION','RETURN_TO_PROCUREMENT')) OR "
            "(issue_type = 'EXCESS' AND resolution_type IN ('ACCEPT_EXCESS','REJECT_EXCESS'))",
            name="ck_supply_acceptance_resolutions_compatible_type",
        ),
        sa.CheckConstraint(
            "(status = 'RESOLVED' AND resolution_type IS NOT NULL AND resolved_by_user_id IS NOT NULL AND resolved_at IS NOT NULL) OR "
            "(status IN ('OPEN','CANCELLED') AND resolution_type IS NULL AND resolved_by_user_id IS NULL AND resolved_at IS NULL)",
            name="ck_supply_acceptance_resolutions_state",
        ),
    )
    op.create_index(
        "ix_supply_acceptance_resolutions_acceptance",
        "supply_acceptance_resolutions",
        ["tenant_id", "supplier_acceptance_id", "status", "created_at"],
    )

    connection = op.get_bind()
    base = (
        "INSERT INTO supply_acceptance_resolutions "
        "(id, tenant_id, supplier_acceptance_id, acceptance_line_id, issue_type, status, quantity, unit_id) "
    )
    connection.execute(sa.text(base +
        "SELECT gen_random_uuid(), line.tenant_id, line.acceptance_id, line.id, 'SHORTAGE', 'OPEN', "
        "line.documented_quantity - line.received_quantity, line.unit_id "
        "FROM supply_supplier_acceptance_lines line JOIN supply_supplier_acceptances acceptance "
        "ON acceptance.tenant_id = line.tenant_id AND acceptance.id = line.acceptance_id "
        "WHERE acceptance.status = 'RECORDED' AND line.documented_quantity > line.received_quantity"
    ))
    connection.execute(sa.text(base +
        "SELECT gen_random_uuid(), line.tenant_id, line.acceptance_id, line.id, 'EXCESS', 'OPEN', "
        "line.accepted_quantity - line.documented_quantity, line.unit_id "
        "FROM supply_supplier_acceptance_lines line JOIN supply_supplier_acceptances acceptance "
        "ON acceptance.tenant_id = line.tenant_id AND acceptance.id = line.acceptance_id "
        "WHERE acceptance.status = 'RECORDED' AND line.documented_quantity IS NOT NULL "
        "AND line.accepted_quantity > line.documented_quantity"
    ))
    connection.execute(sa.text(base +
        "SELECT gen_random_uuid(), line.tenant_id, line.acceptance_id, line.id, 'REJECTED', 'OPEN', "
        "line.rejected_quantity, line.unit_id "
        "FROM supply_supplier_acceptance_lines line JOIN supply_supplier_acceptances acceptance "
        "ON acceptance.tenant_id = line.tenant_id AND acceptance.id = line.acceptance_id "
        "WHERE acceptance.status = 'RECORDED' AND line.rejected_quantity > 0"
    ))

    with op.batch_alter_table("supply_procurement_needs") as batch:
        batch.add_column(sa.Column("acceptance_resolution_id", sa.Uuid(), nullable=True))
        batch.drop_constraint("ck_supply_procurement_needs_source", type_="check")
        batch.drop_constraint("ck_supply_procurement_needs_source_type", type_="check")
        batch.drop_constraint("ck_supply_procurement_needs_reason", type_="check")
        batch.create_check_constraint(
            "ck_supply_procurement_needs_source_type",
            "source_type IN ('REQUEST_LINE','DEPARTMENT_DEBT','ACCEPTANCE_RESOLUTION')",
        )
        batch.create_check_constraint(
            "ck_supply_procurement_needs_reason",
            "reason IN ('INTERNAL_STOCK_DEFICIT','DEBT_CARRY_FORWARD','ACTUAL_SHORTFALL','SUPPLIER_SHORTAGE','SUPPLIER_REJECTION')",
        )
        batch.create_check_constraint(
            "ck_supply_procurement_needs_source",
            "(source_type = 'REQUEST_LINE' AND supply_request_line_id IS NOT NULL AND department_debt_id IS NULL AND basis_stock_calculation_line_id IS NOT NULL AND acceptance_resolution_id IS NULL AND reason = 'INTERNAL_STOCK_DEFICIT') OR "
            "(source_type = 'DEPARTMENT_DEBT' AND department_debt_id IS NOT NULL AND supply_request_line_id IS NULL AND basis_stock_calculation_line_id IS NULL AND acceptance_resolution_id IS NULL AND reason = 'DEBT_CARRY_FORWARD') OR "
            "(source_type = 'ACCEPTANCE_RESOLUTION' AND acceptance_resolution_id IS NOT NULL AND supply_request_line_id IS NULL AND department_debt_id IS NULL AND basis_stock_calculation_line_id IS NULL AND reason IN ('SUPPLIER_SHORTAGE','SUPPLIER_REJECTION'))",
        )
        batch.create_foreign_key(
            "fk_supply_procurement_needs_acceptance_resolution_tenant",
            "supply_acceptance_resolutions", ["tenant_id", "acceptance_resolution_id"],
            ["tenant_id", "id"], ondelete="RESTRICT",
        )
    op.create_index(
        "uq_supply_procurement_needs_acceptance_resolution",
        "supply_procurement_needs", ["tenant_id", "acceptance_resolution_id"],
        unique=True, postgresql_where=sa.text("acceptance_resolution_id IS NOT NULL"),
        sqlite_where=sa.text("acceptance_resolution_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM supply_procurement_needs WHERE source_type = 'ACCEPTANCE_RESOLUTION'"))
    op.drop_index("uq_supply_procurement_needs_acceptance_resolution", table_name="supply_procurement_needs")
    with op.batch_alter_table("supply_procurement_needs") as batch:
        batch.drop_constraint("fk_supply_procurement_needs_acceptance_resolution_tenant", type_="foreignkey")
        batch.drop_constraint("ck_supply_procurement_needs_source", type_="check")
        batch.drop_constraint("ck_supply_procurement_needs_source_type", type_="check")
        batch.drop_constraint("ck_supply_procurement_needs_reason", type_="check")
        batch.create_check_constraint("ck_supply_procurement_needs_source_type", "source_type IN ('REQUEST_LINE','DEPARTMENT_DEBT')")
        batch.create_check_constraint("ck_supply_procurement_needs_reason", "reason IN ('INTERNAL_STOCK_DEFICIT','DEBT_CARRY_FORWARD','ACTUAL_SHORTFALL')")
        batch.create_check_constraint(
            "ck_supply_procurement_needs_source",
            "(source_type = 'REQUEST_LINE' AND supply_request_line_id IS NOT NULL AND department_debt_id IS NULL AND basis_stock_calculation_line_id IS NOT NULL AND reason = 'INTERNAL_STOCK_DEFICIT') OR "
            "(source_type = 'DEPARTMENT_DEBT' AND department_debt_id IS NOT NULL AND supply_request_line_id IS NULL AND basis_stock_calculation_line_id IS NULL AND reason = 'DEBT_CARRY_FORWARD')",
        )
        batch.drop_column("acceptance_resolution_id")
    op.drop_table("supply_acceptance_resolutions")
    op.drop_constraint(
        "uq_supply_supplier_acceptance_lines_tenant_id_acceptance",
        "supply_supplier_acceptance_lines", type_="unique",
    )
