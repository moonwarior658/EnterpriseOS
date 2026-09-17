"""add purchase quantity traceability

Revision ID: 20260917_0054
Revises: 20260917_0053
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0054"
down_revision: str | None = "20260917_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_supply_purchase_request_line_sources_tenant_id",
        "supply_purchase_request_line_sources", ["tenant_id", "id"],
    )
    op.create_table(
        "supply_purchase_allocation_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("allocation_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_request_line_source_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_quantity", sa.Numeric(30, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_purchase_allocation_sources_tenant_id"),
        sa.UniqueConstraint("tenant_id", "allocation_id", "purchase_request_line_source_id", name="uq_supply_purchase_allocation_sources_pair"),
        sa.ForeignKeyConstraint(["tenant_id", "allocation_id"], ["supply_purchase_allocations.tenant_id", "supply_purchase_allocations.id"], name="fk_supply_purchase_allocation_sources_allocation_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "purchase_request_line_source_id"], ["supply_purchase_request_line_sources.tenant_id", "supply_purchase_request_line_sources.id"], name="fk_supply_purchase_allocation_sources_line_source_tenant", ondelete="RESTRICT"),
        sa.CheckConstraint("allocated_quantity > 0", name="ck_supply_purchase_allocation_sources_quantity"),
    )
    op.create_index("ix_supply_purchase_allocation_sources_line_source", "supply_purchase_allocation_sources", ["tenant_id", "purchase_request_line_source_id"])

    op.create_table(
        "supply_supplier_order_line_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("order_line_id", sa.Uuid(), nullable=False),
        sa.Column("allocation_source_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_request_line_source_id", sa.Uuid(), nullable=False),
        sa.Column("source_type_snapshot", sa.String(32), nullable=False),
        sa.Column("procurement_need_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column("planned_quantity", sa.Numeric(30, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_order_line_sources_tenant_id"),
        sa.UniqueConstraint("tenant_id", "order_line_id", "purchase_request_line_source_id", name="uq_supply_supplier_order_line_sources_pair"),
        sa.ForeignKeyConstraint(["tenant_id", "order_line_id"], ["supply_supplier_order_lines.tenant_id", "supply_supplier_order_lines.id"], name="fk_supply_supplier_order_line_sources_order_line_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "allocation_source_id"], ["supply_purchase_allocation_sources.tenant_id", "supply_purchase_allocation_sources.id"], name="fk_supply_supplier_order_line_sources_allocation_source_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "purchase_request_line_source_id"], ["supply_purchase_request_line_sources.tenant_id", "supply_purchase_request_line_sources.id"], name="fk_supply_supplier_order_line_sources_line_source_tenant", ondelete="RESTRICT"),
        sa.CheckConstraint("planned_quantity > 0", name="ck_supply_supplier_order_line_sources_quantity"),
        sa.CheckConstraint("(source_type_snapshot = 'PROCUREMENT_NEED' AND procurement_need_id_snapshot IS NOT NULL) OR (source_type_snapshot = 'MANUAL_FUTURE' AND procurement_need_id_snapshot IS NULL)", name="ck_supply_supplier_order_line_sources_reference"),
    )
    op.create_index("ix_supply_supplier_order_line_sources_line", "supply_supplier_order_line_sources", ["tenant_id", "order_line_id"])
    op.create_index("ix_supply_supplier_order_line_sources_line_source", "supply_supplier_order_line_sources", ["tenant_id", "purchase_request_line_source_id"])

    op.create_table(
        "supply_supplier_acceptance_line_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("acceptance_line_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_order_line_source_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_quantity", sa.Numeric(30, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supply_supplier_acceptance_line_sources_tenant_id"),
        sa.UniqueConstraint("tenant_id", "acceptance_line_id", "supplier_order_line_source_id", name="uq_supply_supplier_acceptance_line_sources_pair"),
        sa.ForeignKeyConstraint(["tenant_id", "acceptance_line_id"], ["supply_supplier_acceptance_lines.tenant_id", "supply_supplier_acceptance_lines.id"], name="fk_supply_accept_line_sources_line_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_order_line_source_id"], ["supply_supplier_order_line_sources.tenant_id", "supply_supplier_order_line_sources.id"], name="fk_supply_supplier_acceptance_line_sources_order_source_tenant", ondelete="RESTRICT"),
        sa.CheckConstraint("accepted_quantity > 0", name="ck_supply_supplier_acceptance_line_sources_quantity"),
    )
    op.create_index("ix_supply_supplier_acceptance_line_sources_order_source", "supply_supplier_acceptance_line_sources", ["tenant_id", "supplier_order_line_source_id"])

    # A single source is the only legacy split that is intrinsically known.
    # Multiple allocations are backfilled only when their total does not exceed
    # that source; otherwise the complete legacy path remains explicitly unknown.
    op.execute("""
        INSERT INTO supply_purchase_allocation_sources
            (id, tenant_id, allocation_id, purchase_request_line_source_id, allocated_quantity)
        SELECT gen_random_uuid(), a.tenant_id, a.id, s.id,
               LEAST(a.quantity_base, s.quantity)
        FROM supply_purchase_allocations a
        JOIN supply_purchase_request_line_sources s
          ON s.tenant_id = a.tenant_id AND s.purchase_request_line_id = a.purchase_request_line_id
        WHERE (SELECT count(*) FROM supply_purchase_request_line_sources x
               WHERE x.tenant_id = a.tenant_id
                 AND x.purchase_request_line_id = a.purchase_request_line_id) = 1
          AND (
              (SELECT count(*) FROM supply_purchase_allocations x
               WHERE x.tenant_id = a.tenant_id
                 AND x.purchase_request_line_id = a.purchase_request_line_id) = 1
              OR
              (SELECT sum(x.quantity_base) FROM supply_purchase_allocations x
               WHERE x.tenant_id = a.tenant_id
                 AND x.purchase_request_line_id = a.purchase_request_line_id) <= s.quantity
          )
    """)
    op.execute("""
        INSERT INTO supply_supplier_order_line_sources
            (id, tenant_id, order_line_id, allocation_source_id,
             purchase_request_line_source_id, source_type_snapshot,
             procurement_need_id_snapshot, planned_quantity)
        SELECT gen_random_uuid(), ol.tenant_id, ol.id, als.id,
               als.purchase_request_line_source_id, prs.source_type,
               prs.procurement_need_id, als.allocated_quantity
        FROM supply_supplier_order_lines ol
        JOIN supply_purchase_allocation_sources als
          ON als.tenant_id = ol.tenant_id AND als.allocation_id = ol.source_allocation_id
        JOIN supply_purchase_request_line_sources prs
          ON prs.tenant_id = als.tenant_id AND prs.id = als.purchase_request_line_source_id
    """)
    op.execute("""
        INSERT INTO supply_supplier_acceptance_line_sources
            (id, tenant_id, acceptance_line_id, supplier_order_line_source_id, accepted_quantity)
        SELECT gen_random_uuid(), al.tenant_id, al.id, ols.id, al.accepted_quantity
        FROM supply_supplier_acceptance_lines al
        JOIN supply_supplier_acceptances a
          ON a.tenant_id = al.tenant_id AND a.id = al.acceptance_id
        JOIN supply_supplier_order_line_sources ols
          ON ols.tenant_id = al.tenant_id AND ols.order_line_id = al.supplier_order_line_id
        WHERE a.status = 'RECORDED' AND al.accepted_quantity > 0
          AND (SELECT count(*) FROM supply_supplier_order_line_sources x
               WHERE x.tenant_id = ols.tenant_id AND x.order_line_id = ols.order_line_id) = 1
          AND (SELECT sum(x.accepted_quantity)
               FROM supply_supplier_acceptance_lines x
               JOIN supply_supplier_acceptances xa
                 ON xa.tenant_id = x.tenant_id AND xa.id = x.acceptance_id
               WHERE x.tenant_id = al.tenant_id
                 AND x.supplier_order_line_id = al.supplier_order_line_id
                 AND xa.status = 'RECORDED') <= ols.planned_quantity
    """)


def downgrade() -> None:
    op.drop_table("supply_supplier_acceptance_line_sources")
    op.drop_table("supply_supplier_order_line_sources")
    op.drop_table("supply_purchase_allocation_sources")
    op.drop_constraint(
        "uq_supply_purchase_request_line_sources_tenant_id",
        "supply_purchase_request_line_sources", type_="unique",
    )
