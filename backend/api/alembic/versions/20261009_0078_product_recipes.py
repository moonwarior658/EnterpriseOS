"""K5B immutable recipe versions and observations; no schedule/data bootstrap."""
from alembic import op
import sqlalchemy as sa
revision = '20261009_0078'
down_revision = '20261009_0077'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('product_recipe_versions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('chart_id', sa.Uuid(), nullable=False),
        sa.Column('source_product_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id','source_id'], ['sales_sync_states.tenant_id','sales_sync_states.source_id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('tenant_id','source_id','chart_id','kind','content_hash', name='uq_recipe_content'),
        sa.CheckConstraint("kind IN ('SOURCE','PREPARED')", name='ck_recipe_kind'))
    op.create_table('product_recipe_observations',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('execution_id', sa.Uuid(), nullable=False),
        sa.Column('effective_on', sa.Date(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id','product_id'], ['product_knowledge_products.tenant_id','product_knowledge_products.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id','source_id'], ['sales_sync_states.tenant_id','sales_sync_states.source_id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('tenant_id','execution_id','product_id', name='uq_recipe_execution_product'),
        sa.CheckConstraint("status IN ('INCOMPLETE','CONFLICT','UNCONFIRMED')", name='ck_recipe_status'))
    op.create_index('ix_recipe_observation', 'product_recipe_observations', ['tenant_id','product_id','observed_at'])
    op.execute("""CREATE FUNCTION reject_recipe_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'RECIPE_HISTORY_IMMUTABLE'; END $$""")
    for table in ('product_recipe_versions', 'product_recipe_observations'):
        op.execute(f'CREATE TRIGGER immutable_recipe BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_recipe_mutation()')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM product_recipe_versions) OR EXISTS (SELECT 1 FROM product_recipe_observations)')).scalar():
        raise RuntimeError('RECIPE_HISTORY_EXISTS: retain schema')
    op.drop_table('product_recipe_observations')
    op.drop_table('product_recipe_versions')
    op.execute('DROP FUNCTION reject_recipe_mutation()')
