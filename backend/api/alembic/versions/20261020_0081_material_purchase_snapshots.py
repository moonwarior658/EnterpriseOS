"""R-M2 immutable purchase observations only; no seeds or schedules."""
from alembic import op
import sqlalchemy as sa
revision = '20261020_0081'
down_revision = '20261020_0080'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('material_purchase_snapshots',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('execution_id', sa.Uuid(), sa.ForeignKey('automation_executions.execution_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('amount', sa.String(100)),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id','product_id'], ['raw_material_profiles.tenant_id','raw_material_profiles.product_id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('tenant_id','product_id','execution_id', name='uq_material_purchase_execution'),
        sa.CheckConstraint("status IN ('READY','BLOCKED','NO_DATA')", name='ck_material_purchase_status'),
        sa.CheckConstraint("(status = 'READY' AND amount IS NOT NULL) OR (status <> 'READY' AND amount IS NULL)", name='ck_material_purchase_amount'))
    for column in ('tenant_id','product_id','observed_at'):
        op.create_index('ix_material_purchase_snapshots_'+column, 'material_purchase_snapshots', [column])
    op.execute("""CREATE FUNCTION enforce_material_purchase_execution_scope() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM automation_executions e WHERE e.execution_id = NEW.execution_id
            AND e.tenant_id = NEW.tenant_id AND e.automation_type = 'materials.sync_iiko_purchase_price'
            AND e.payload->>'product_id' = NEW.product_id::text) THEN
            RAISE EXCEPTION 'MATERIAL_PURCHASE_EXECUTION_SCOPE';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute('CREATE TRIGGER material_purchase_execution_scope BEFORE INSERT ON material_purchase_snapshots FOR EACH ROW EXECUTE FUNCTION enforce_material_purchase_execution_scope()')
    op.execute('CREATE TRIGGER immutable_material_purchase BEFORE UPDATE OR DELETE ON material_purchase_snapshots FOR EACH ROW EXECUTE FUNCTION reject_material_history_mutation()')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM material_purchase_snapshots)')).scalar():
        raise RuntimeError('MATERIAL_PURCHASE_HISTORY_EXISTS: retain snapshots')
    op.drop_table('material_purchase_snapshots')
    op.execute('DROP FUNCTION enforce_material_purchase_execution_scope()')
