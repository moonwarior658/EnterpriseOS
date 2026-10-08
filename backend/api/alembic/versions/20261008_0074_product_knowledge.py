"""Add isolated source-first product knowledge catalog, no data backfill."""
from alembic import op
import sqlalchemy as sa

revision = '20261008_0074'
down_revision = '20261006_0073'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('product_knowledge_batches',
        sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False), sa.Column('plan_hash', sa.String(64), nullable=False),
        sa.Column('report', sa.JSON(), nullable=False), sa.Column('initial_status', sa.String(16), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True)),
        sa.Column('rolled_back_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT')),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_pk_batch_tenant_id'),
        sa.UniqueConstraint('tenant_id', 'source_id', 'plan_hash', name='uq_pk_batch_plan'))
    op.create_table('product_knowledge_products',
        sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False), sa.Column('iiko_product_id', sa.Uuid(), nullable=False),
        sa.Column('supply_product_id', sa.Uuid()), sa.Column('batch_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(500), nullable=False), sa.Column('sku', sa.String(160)),
        sa.Column('unit_id', sa.Uuid(), nullable=False), sa.Column('unit_name', sa.String(160), nullable=False),
        sa.Column('unit_weight_kg', sa.Numeric()), sa.Column('sale_mode', sa.String(16), nullable=False),
        sa.Column('sale_status', sa.String(16), nullable=False), sa.Column('category_id', sa.Uuid()),
        sa.Column('category_name', sa.String(240)), sa.Column('description', sa.String()),
        sa.Column('source_deleted', sa.Boolean(), nullable=False), sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False), sa.Column('published', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_pk_product_tenant_id'),
        sa.UniqueConstraint('tenant_id', 'source_id', 'iiko_product_id', name='uq_pk_product_source_uuid'),
        sa.ForeignKeyConstraint(['tenant_id', 'source_id'], ['sales_sync_states.tenant_id', 'sales_sync_states.source_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id', 'supply_product_id'], ['supply_products.tenant_id', 'supply_products.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id', 'batch_id'], ['product_knowledge_batches.tenant_id', 'product_knowledge_batches.id'], ondelete='RESTRICT'),
        sa.CheckConstraint("sale_status IN ('ON_SALE', 'OFF_SALE')", name='ck_pk_sale_status'),
        sa.CheckConstraint("sale_mode IN ('UNKNOWN', 'PORTION', 'WEIGHT')", name='ck_pk_sale_mode'),
        sa.CheckConstraint('unit_weight_kg IS NULL OR unit_weight_kg > 0', name='ck_pk_weight'))
    op.create_table('product_knowledge_prices',
        sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False), sa.Column('department_id', sa.Uuid(), nullable=False),
        sa.Column('valid_from', sa.Date(), nullable=False), sa.Column('valid_to', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(20, 6), nullable=False), sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('price_unit', sa.String(160), nullable=False), sa.Column('evidence', sa.String(500), nullable=False),
        sa.Column('verified_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id', 'product_id'], ['product_knowledge_products.tenant_id', 'product_knowledge_products.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id', 'department_id'], ['departments.tenant_id', 'departments.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('tenant_id', 'product_id', 'department_id', 'valid_from', 'valid_to', name='uq_pk_price_interval'),
        sa.CheckConstraint('amount >= 0', name='ck_pk_price_amount'),
        sa.CheckConstraint('valid_to > valid_from', name='ck_pk_price_dates'))


def downgrade():
    # Operational rollback is unpublication, never schema downgrade with business data.
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT count(*) FROM product_knowledge_batches')).scalar():
        raise RuntimeError('PRODUCT_KNOWLEDGE_DATA_EXISTS: use batch unpublication')
    op.drop_table('product_knowledge_prices')
    op.drop_table('product_knowledge_products')
    op.drop_table('product_knowledge_batches')
