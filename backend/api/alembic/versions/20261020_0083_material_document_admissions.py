"""Exact-source management purchase/packaging decisions. No automatic approvals."""
from alembic import op
import sqlalchemy as sa
revision='20261020_0083'
down_revision='20261020_0082'
branch_labels=depends_on=None


def upgrade():
    op.create_unique_constraint('uq_material_purchase_owner','material_purchase_snapshots',['tenant_id','product_id','id'])
    op.create_table('material_document_admissions',
        sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('tenant_id',sa.String(64),nullable=False),
        sa.Column('product_id',sa.Uuid(),nullable=False),sa.Column('snapshot_id',sa.Uuid(),nullable=False),
        sa.Column('request_id',sa.Uuid(),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('scope_key',sa.String(64),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('kind',sa.String(24),nullable=False),sa.Column('action',sa.String(8),nullable=False),
        sa.Column('source_id',sa.String(64),nullable=False),sa.Column('warehouse_id',sa.Uuid(),nullable=False),
        sa.Column('document_id',sa.Uuid(),nullable=False),sa.Column('document_hash',sa.String(64),nullable=False),
        sa.Column('line_num',sa.String(32),nullable=False),sa.Column('line_hash',sa.String(64),nullable=False),
        sa.Column('evidence',sa.String(2000),nullable=False),sa.Column('comment',sa.String(2000),nullable=False),
        sa.Column('verification',sa.JSON(),nullable=False),sa.Column('actor_user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.ForeignKeyConstraint(['tenant_id','product_id','snapshot_id'],['material_purchase_snapshots.tenant_id','material_purchase_snapshots.product_id','material_purchase_snapshots.id'],ondelete='RESTRICT'),
        sa.UniqueConstraint('tenant_id','request_id',name='uq_material_admission_request'),
        sa.UniqueConstraint('scope_key','revision',name='uq_material_admission_revision'),
        sa.CheckConstraint("kind IN ('EMPLOYEE_PURCHASE','BASE_UNIT_CONTAINER')",name='ck_material_admission_kind'),
        sa.CheckConstraint("action IN ('GRANT','REVOKE') AND revision>0",name='ck_material_admission_action'),
        sa.CheckConstraint("kind <> 'BASE_UNIT_CONTAINER' OR line_num <> ''",name='ck_material_admission_line'),
        sa.CheckConstraint("length(trim(evidence))>=3 AND length(trim(comment))>=3",name='ck_material_admission_proof'))
    for col in ('tenant_id','product_id','scope_key'):op.create_index('ix_material_document_admissions_'+col,'material_document_admissions',[col])
    op.execute('''CREATE FUNCTION guard_material_admission_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE prior material_document_admissions%ROWTYPE;
    BEGIN
      PERFORM 1 FROM raw_material_profiles WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id FOR UPDATE;
      IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.actor_user_id AND tenant_id=NEW.tenant_id) THEN
        RAISE EXCEPTION 'MATERIAL_ADMISSION_ACTOR_SCOPE';
      END IF;
      IF NEW.source_id<>'244d6eaf9c7c106993d10feb0ff9883dbdb73101cd3a2ab6852c9ba5b9907401'
        OR NEW.warehouse_id<>'1c22edc0-7ded-41c9-b781-0389462c7247'::uuid THEN
        RAISE EXCEPTION 'MATERIAL_ADMISSION_SOURCE_SCOPE';
      END IF;
      SELECT * INTO prior FROM material_document_admissions WHERE scope_key=NEW.scope_key ORDER BY revision DESC LIMIT 1;
      IF NEW.revision<>COALESCE(prior.revision,0)+1 OR NEW.action=COALESCE(prior.action,'REVOKE') THEN
        RAISE EXCEPTION 'MATERIAL_ADMISSION_REVISION_CONFLICT';
      END IF;
      RETURN NEW;
    END $$''')
    op.execute('CREATE TRIGGER material_admission_insert BEFORE INSERT ON material_document_admissions FOR EACH ROW EXECUTE FUNCTION guard_material_admission_insert()')
    op.execute('CREATE TRIGGER immutable_material_admission BEFORE UPDATE OR DELETE ON material_document_admissions FOR EACH ROW EXECUTE FUNCTION reject_material_history_mutation()')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM material_document_admissions)')).scalar():
        raise RuntimeError('MATERIAL_ADMISSION_HISTORY_EXISTS: retain decisions')
    op.drop_table('material_document_admissions')
    op.execute('DROP FUNCTION guard_material_admission_insert()')
    op.drop_constraint('uq_material_purchase_owner','material_purchase_snapshots',type_='unique')
