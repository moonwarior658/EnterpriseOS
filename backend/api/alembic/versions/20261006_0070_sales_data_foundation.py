"""Sales raw facts and checkpoints; no guessed identities or production activation.

Revision ID: 20261006_0070
Revises: 20261006_0069
"""
from alembic import op
import sqlalchemy as sa

revision = "20261006_0070"
down_revision = "20261006_0069"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("iiko_department_mappings", sa.Column("olap_department_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint("uq_iiko_department_mapping_olap", "iiko_department_mappings", ["tenant_id", "olap_department_id"])
    op.create_table("sales_sync_states",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("source_timezone", sa.String(64), nullable=False),
        sa.Column("history_from", sa.Date(), nullable=False),
        sa.Column("backfill_next", sa.Date(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
    )
    op.create_table("sales_day_syncs",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("business_date", sa.Date(), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "source_id"], ["sales_sync_states.tenant_id", "sales_sync_states.source_id"], ondelete="RESTRICT"),
    )
    op.create_table("sales_facts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime()),
        *[sa.Column(name, sa.Uuid(), nullable=False) for name in ("iiko_department_id", "iiko_order_id", "iiko_item_id", "iiko_product_id")],
        *[sa.Column(name, sa.Uuid()) for name in ("iiko_group_id", "source_order_id", "sold_with_item_id", "employee_id", "department_id", "product_id")],
        *[sa.Column(name, sa.String(160)) for name in ("iiko_employee_id", "order_waiter_id", "item_waiter_id")],
        sa.Column("product_name", sa.String(500)), sa.Column("product_category", sa.String(500)),
        *[sa.Column(name, sa.Numeric(), nullable=False) for name in ("quantity", "amount_before_discount", "amount_after_discount", "return_amount")],
        *[sa.Column(name, sa.Boolean(), nullable=False) for name in ("is_free", "is_returned", "is_deleted", "is_present")],
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "source_id"], ["sales_sync_states.tenant_id", "sales_sync_states.source_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "source_id", "iiko_department_id", "iiko_order_id", "iiko_item_id", name="uq_sales_fact_source_identity"),
        sa.ForeignKeyConstraint(["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["supply_products.tenant_id", "supply_products.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_sales_fact_day", "sales_facts", ["tenant_id", "source_id", "business_date"])
    op.create_index("ix_sales_fact_source_order", "sales_facts", ["tenant_id", "source_id", "source_order_id"])


def downgrade():
    # Explicit rollback removes this feature's raw history; no existing business data touched.
    op.drop_table("sales_facts")
    op.drop_table("sales_day_syncs")
    op.drop_table("sales_sync_states")
    op.drop_constraint("uq_iiko_department_mapping_olap", "iiko_department_mappings", type_="unique")
    op.drop_column("iiko_department_mappings", "olap_department_id")
