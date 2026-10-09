"""K5C observations/Office verification only; no production values or schedules."""
from alembic import op
import sqlalchemy as sa
revision = '20261009_0079'
down_revision = '20261009_0078'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('product_cost_observations',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('tenant_id',sa.String(64),nullable=False),
        sa.Column('source_id',sa.String(64),nullable=False),
        sa.Column('product_id',sa.Uuid(),nullable=False),
        sa.Column('execution_id',sa.Uuid(),nullable=False),
        sa.Column('stock_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('observed_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),
        sa.Column('context_hash',sa.String(64),nullable=False),
        sa.Column('method_hash',sa.String(64),nullable=True),
        sa.Column('content_hash',sa.String(64),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),
        sa.UniqueConstraint('tenant_id','id',name='uq_cost_observation_tenant'),
        sa.UniqueConstraint('tenant_id','execution_id','product_id',name='uq_cost_execution_product'),
        sa.ForeignKeyConstraint(['tenant_id','product_id'],['product_knowledge_products.tenant_id','product_knowledge_products.id'],ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id','source_id'],['sales_sync_states.tenant_id','sales_sync_states.source_id'],ondelete='RESTRICT'),
        sa.CheckConstraint("status IN ('UNVERIFIED','INCOMPLETE')",name='ck_cost_status'))
    op.create_index('ix_cost_latest','product_cost_observations',['tenant_id','product_id','stock_at','observed_at'])
    op.create_table('product_cost_verifications',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('tenant_id',sa.String(64),nullable=False),
        sa.Column('observation_id',sa.Uuid(),nullable=False),
        sa.Column('confirmed_by_user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('confirmed_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),
        sa.UniqueConstraint('tenant_id','observation_id',name='uq_cost_verification'),
        sa.ForeignKeyConstraint(['tenant_id','observation_id'],['product_cost_observations.tenant_id','product_cost_observations.id'],ondelete='RESTRICT'))
    op.execute("""CREATE FUNCTION reject_cost_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'COST_HISTORY_IMMUTABLE'; END $$""")
    for table in ('product_cost_observations','product_cost_verifications'):
        op.execute(f'CREATE TRIGGER immutable_cost BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_cost_mutation()')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM product_cost_observations) OR EXISTS (SELECT 1 FROM product_cost_verifications)')).scalar():
        raise RuntimeError('COST_HISTORY_EXISTS: retain schema')
    op.drop_table('product_cost_verifications')
    op.drop_table('product_cost_observations')
    op.execute('DROP FUNCTION reject_cost_mutation()')
