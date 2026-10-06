"""Append-only monthly network KPI and revenue targets.

Revision ID: 20261006_0071
Revises: 20261006_0070
"""
from alembic import op
import sqlalchemy as sa

revision = "20261006_0071"
down_revision = "20261006_0070"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("sales_targets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(24, 6), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "metric", "month", "revision", name="uq_sales_target_revision"),
        sa.CheckConstraint("metric IN ('average_check', 'fullness', 'revenue')", name="ck_sales_target_metric"),
        sa.CheckConstraint("value > 0 AND value < 1000000000000000000", name="ck_sales_target_value"),
        sa.CheckConstraint("revision > 0", name="ck_sales_target_revision"),
        sa.CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_sales_target_month"),
    )
    op.execute("""CREATE FUNCTION sales_targets_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'sales_targets are append only'; END; $$""")
    op.execute("CREATE TRIGGER sales_targets_append_only BEFORE UPDATE OR DELETE ON sales_targets FOR EACH ROW EXECUTE FUNCTION sales_targets_append_only()")


def downgrade():
    # Explicit feature rollback removes its target history, never touches sale facts.
    op.drop_table("sales_targets")
    op.execute("DROP FUNCTION sales_targets_append_only()")
