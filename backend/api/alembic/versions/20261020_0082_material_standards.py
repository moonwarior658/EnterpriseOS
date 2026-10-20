"""Version-bound material allowances and proven package conversions; no seeds."""
from alembic import op
import sqlalchemy as sa
revision='20261020_0082'
down_revision='20261020_0081'
branch_labels=depends_on=None


def upgrade():
    op.drop_constraint('ck_material_primary_self_rm1','material_specification_approvals',type_='check')
    for table in ('material_product_allowances','material_unit_conversions'):
        common=[sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('tenant_id',sa.String(64),nullable=False),
            sa.Column('product_id',sa.Uuid(),nullable=False),sa.Column('specification_id',sa.Uuid(),nullable=False),
            sa.ForeignKeyConstraint(['tenant_id','product_id','specification_id'],['material_specification_versions.tenant_id','material_specification_versions.product_id','material_specification_versions.id'],ondelete='RESTRICT')]
        if table=='material_product_allowances':
            extra=[sa.Column('target_product_id',sa.Uuid(),nullable=False),sa.Column('role',sa.String(16),nullable=False),
                sa.ForeignKeyConstraint(['tenant_id','target_product_id'],['supply_products.tenant_id','supply_products.id'],ondelete='RESTRICT'),
                sa.UniqueConstraint('specification_id','target_product_id',name='uq_material_allowance_target'),
                sa.CheckConstraint("role IN ('PRIMARY','RESERVE')",name='ck_material_allowance_role')]
        else:
            extra=[sa.Column(n,sa.Uuid(),nullable=n=='container_id') for n in ('from_unit_id','to_unit_id','supplier_iiko_id','container_id')]+[
                sa.Column('factor',sa.Numeric(24,12),nullable=False),sa.Column('valid_from',sa.Date(),nullable=False),sa.Column('valid_to',sa.Date(),nullable=False),
                sa.CheckConstraint('factor > 0 AND factor <= 100000',name='ck_material_conversion_factor'),
                sa.CheckConstraint('valid_to > valid_from AND from_unit_id <> to_unit_id',name='ck_material_conversion_period')]
        op.create_table(table,*(common+extra))
        op.execute(f'CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_material_history_mutation()')
    op.create_index('uq_material_single_primary','material_product_allowances',['specification_id'],unique=True,postgresql_where=sa.text("role='PRIMARY'"))
    op.execute('''CREATE FUNCTION guard_material_standard_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM 1 FROM material_specification_versions WHERE id=NEW.specification_id FOR UPDATE;
      IF EXISTS(SELECT 1 FROM material_specification_approvals WHERE specification_id=NEW.specification_id) THEN
        RAISE EXCEPTION 'MATERIAL_STANDARD_ALREADY_APPROVED';
      END IF;
      IF TG_TABLE_NAME='material_unit_conversions' THEN
        IF EXISTS(SELECT 1 FROM material_unit_conversions c WHERE c.specification_id=NEW.specification_id
          AND c.from_unit_id=NEW.from_unit_id AND c.to_unit_id=NEW.to_unit_id
          AND c.supplier_iiko_id=NEW.supplier_iiko_id AND c.container_id IS NOT DISTINCT FROM NEW.container_id
          AND c.valid_from<NEW.valid_to AND NEW.valid_from<c.valid_to) THEN
          RAISE EXCEPTION 'MATERIAL_CONVERSION_OVERLAP';
        END IF;
      END IF;
      RETURN NEW;
    END $$''')
    for table in ('material_product_allowances','material_unit_conversions'):
        op.execute(f'CREATE TRIGGER guard_standard_insert BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION guard_material_standard_insert()')
    op.execute('''CREATE FUNCTION guard_material_primary_approval() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM 1 FROM material_specification_versions WHERE id=NEW.specification_id FOR UPDATE;
      IF EXISTS(SELECT 1 FROM material_product_allowances WHERE specification_id=NEW.specification_id) THEN
        IF NOT EXISTS(SELECT 1 FROM material_product_allowances WHERE specification_id=NEW.specification_id
          AND role='PRIMARY' AND target_product_id=NEW.primary_product_id) THEN
          RAISE EXCEPTION 'MATERIAL_PRIMARY_NOT_ALLOWED';
        END IF;
      ELSIF NEW.primary_product_id<>NEW.product_id THEN RAISE EXCEPTION 'MATERIAL_PRIMARY_UNCONFIRMED';
      END IF;
      RETURN NEW;
    END $$''')
    op.execute('CREATE TRIGGER guard_material_primary BEFORE INSERT ON material_specification_approvals FOR EACH ROW EXECUTE FUNCTION guard_material_primary_approval()')


def downgrade():
    bind=op.get_bind()
    for table in ('material_product_allowances','material_unit_conversions'):
        if bind.execute(sa.text(f'SELECT EXISTS(SELECT 1 FROM {table})')).scalar():
            raise RuntimeError('MATERIAL_STANDARD_HISTORY_EXISTS: retain standards')
    op.execute('DROP TRIGGER guard_material_primary ON material_specification_approvals')
    op.execute('DROP FUNCTION guard_material_primary_approval()')
    op.drop_table('material_unit_conversions');op.drop_table('material_product_allowances')
    op.execute('DROP FUNCTION guard_material_standard_insert()')
    op.create_check_constraint('ck_material_primary_self_rm1','material_specification_approvals','primary_product_id=product_id')
