"""K3 bounded immutable price observations; no seed/backfill."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0076'
down_revision = '20261009_0075'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('product_knowledge_price_snapshots',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('plan_hash', sa.String(64), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id', 'source_id'], ['sales_sync_states.tenant_id', 'sales_sync_states.source_id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('tenant_id', 'source_id', 'plan_hash', name='uq_pk_price_snapshot_hash'),
        sa.CheckConstraint('date_to > date_from', name='ck_pk_price_snapshot_dates'))
    op.create_index('ix_pk_price_snapshot_lookup', 'product_knowledge_price_snapshots', ['tenant_id', 'source_id', 'observed_at'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM product_knowledge_price_snapshots)')).scalar():
        raise RuntimeError('PRODUCT_PRICE_SNAPSHOTS_EXIST: retain price history')
    op.drop_table('product_knowledge_price_snapshots')
