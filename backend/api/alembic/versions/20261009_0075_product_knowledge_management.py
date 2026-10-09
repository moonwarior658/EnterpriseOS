"""K2 local content, soft deletion, verification and optimistic version; preserve K1."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0075'
down_revision = '20261008_0074'
branch_labels = None
depends_on = None


def upgrade():
    table = 'product_knowledge_products'
    op.add_column(table, sa.Column('local_name', sa.String(500)))
    for key in ('local_description', 'characteristics', 'composition', 'allergens', 'storage', 'training'):
        op.add_column(table, sa.Column(key, sa.String(10000)))
    op.add_column(table, sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column(table, sa.Column('deleted_at', sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column('verified_at', sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column('verified_by_employee_id', sa.Uuid()))
    op.add_column(table, sa.Column('verified_by_name', sa.String(240)))
    op.create_check_constraint('ck_pk_version', table, 'version > 0')
    op.create_foreign_key('fk_pk_verified_employee', table, 'employees',
                         ['tenant_id', 'verified_by_employee_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_index('ix_pk_work_catalog', table, ['tenant_id', 'published', 'deleted_at', 'verified_at'])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("""SELECT EXISTS (SELECT 1 FROM product_knowledge_products
        WHERE version > 1 OR local_name IS NOT NULL OR local_description IS NOT NULL
        OR characteristics IS NOT NULL OR composition IS NOT NULL OR allergens IS NOT NULL
        OR storage IS NOT NULL OR training IS NOT NULL OR deleted_at IS NOT NULL
        OR verified_at IS NOT NULL OR verified_by_employee_id IS NOT NULL OR verified_by_name IS NOT NULL)
        OR EXISTS (SELECT 1 FROM audit_events WHERE entity_type = 'ProductKnowledgeProduct')""")).scalar():
        raise RuntimeError('PRODUCT_KNOWLEDGE_K2_DATA_EXISTS: retain schema and audit')
    table = 'product_knowledge_products'
    op.drop_index('ix_pk_work_catalog', table_name=table)
    op.drop_constraint('fk_pk_verified_employee', table, type_='foreignkey')
    op.drop_constraint('ck_pk_version', table, type_='check')
    for key in ('verified_by_name', 'verified_by_employee_id', 'verified_at', 'deleted_at', 'version',
                'training', 'storage', 'allergens', 'composition', 'characteristics', 'local_description', 'local_name'):
        op.drop_column(table, key)
