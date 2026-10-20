"""R-M1 additive Supply knowledge; no seed, collection or schedules."""
from alembic import op
import sqlalchemy as sa

revision = '20261020_0080'
down_revision = '20261009_0079'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('raw_material_profiles',
        sa.Column('product_id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('archived', sa.Boolean(), nullable=False),
        sa.Column('photo_hash', sa.String(64)),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'product_id', name='uq_material_profile_tenant'),
        sa.ForeignKeyConstraint(['tenant_id', 'product_id'], ['supply_products.tenant_id', 'supply_products.id'], ondelete='RESTRICT'),
        sa.CheckConstraint("kind IN ('RAW_MATERIAL','PACKAGING')", name='ck_material_kind'),
        sa.CheckConstraint('version > 0', name='ck_material_version'))
    op.create_table('material_specification_versions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'product_id', 'id', name='uq_material_spec_owner'),
        sa.UniqueConstraint('tenant_id', 'product_id', 'revision', name='uq_material_spec_revision'),
        sa.ForeignKeyConstraint(['tenant_id', 'product_id'], ['raw_material_profiles.tenant_id', 'raw_material_profiles.product_id'], ondelete='RESTRICT'),
        sa.CheckConstraint('revision > 0', name='ck_material_spec_revision'))
    op.create_table('material_specification_approvals',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('specification_id', sa.Uuid(), nullable=False),
        sa.Column('primary_product_id', sa.Uuid(), nullable=False),
        sa.Column('confirmed_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('specification_id', name='uq_material_spec_approval'),
        sa.ForeignKeyConstraint(['tenant_id', 'product_id', 'specification_id'], ['material_specification_versions.tenant_id', 'material_specification_versions.product_id', 'material_specification_versions.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id', 'primary_product_id'], ['supply_products.tenant_id', 'supply_products.id'], ondelete='RESTRICT'),
        sa.CheckConstraint('primary_product_id = product_id', name='ck_material_primary_self_rm1'))
    op.execute("""CREATE FUNCTION reject_material_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'MATERIAL_HISTORY_IMMUTABLE'; END $$""")
    for table in ('material_specification_versions', 'material_specification_approvals'):
        op.execute(f'CREATE TRIGGER immutable_material_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_material_history_mutation()')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM raw_material_profiles)')).scalar():
        raise RuntimeError('MATERIAL_KNOWLEDGE_EXISTS: retain schema and private photos')
    op.drop_table('material_specification_approvals')
    op.drop_table('material_specification_versions')
    op.drop_table('raw_material_profiles')
    op.execute('DROP FUNCTION reject_material_history_mutation()')
