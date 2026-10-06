"""Indexed receipt traversal and fenced short-transaction background sync lease.

Revision ID: 20261006_0072
Revises: 20261006_0071
"""
from alembic import op
import sqlalchemy as sa

revision = '20261006_0072'
down_revision = '20261006_0071'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_sales_fact_order_present', 'sales_facts',
                    ['tenant_id', 'source_id', 'iiko_order_id'], postgresql_where=sa.text('is_present'))
    op.create_index('ix_sales_fact_item', 'sales_facts', ['tenant_id', 'source_id', 'iiko_item_id'])
    op.add_column('sales_sync_states', sa.Column('lease_token', sa.Uuid(), nullable=True))
    op.add_column('sales_sync_states', sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('sales_sync_states', 'lease_until')
    op.drop_column('sales_sync_states', 'lease_token')
    op.drop_index('ix_sales_fact_item', table_name='sales_facts')
    op.drop_index('ix_sales_fact_order_present', table_name='sales_facts')
