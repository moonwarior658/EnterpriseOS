"""K4 local EOS photo pointer; blobs and action history are retained."""
from alembic import op
import sqlalchemy as sa
revision = '20261009_0077'
down_revision = '20261009_0076'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product_knowledge_products', sa.Column('local_photo_hash', sa.String(64)))
    op.create_check_constraint('ck_pk_photo_hash', 'product_knowledge_products',
                               "local_photo_hash IS NULL OR local_photo_hash ~ '^[a-f0-9]{64}$'")


def downgrade():
    if op.get_bind().execute(sa.text("""SELECT EXISTS (SELECT 1 FROM product_knowledge_products WHERE local_photo_hash IS NOT NULL)
        OR EXISTS (SELECT 1 FROM audit_events WHERE entity_type='ProductKnowledgeProduct' AND operation IN ('PHOTO_UPLOAD','PHOTO_DELETE'))""")).scalar():
        raise RuntimeError('PRODUCT_PHOTO_HISTORY_EXISTS: retain schema and files')
    op.drop_constraint('ck_pk_photo_hash', 'product_knowledge_products', type_='check')
    op.drop_column('product_knowledge_products', 'local_photo_hash')
