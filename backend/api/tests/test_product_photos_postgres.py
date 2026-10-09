import unittest
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.models.user import User
from app.models.audit import AuditEvent
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from app.schemas.product_knowledge import ProductCommand
from app.product_knowledge import media
from tests import test_product_knowledge_postgres as k1
from tests.test_product_photos import image_bytes


@unittest.skipUnless(k1.URL, 'PRODUCT_KNOWLEDGE_TEST_DATABASE_URL not configured')
class ProductPhotoPostgresTests(unittest.TestCase):
    load=k1.ProductKnowledgePostgresTests.load
    def setUp(self):
        k1.ProductKnowledgePostgresTests.setUp(self);self.load();self.storage=TemporaryDirectory()
        with self.sessions() as db:self.pid=db.scalar(select(Product.id).where(Product.tenant_id==self.tenant))
    def tearDown(self):
        self.storage.cleanup();self.engine.dispose()
    def perform(self, body, content):
        with self.sessions.begin() as db:
            return media.mutate(db,db.get(User,self.actor),self.pid,body,self.storage.name,content=content,content_type='image/png').version
    def test_concurrent_upload_conflict_delete_retry_and_persistent_read(self):
        body=ProductCommand(expected_version=1,reason='PG photo')
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(lambda _:self.perform(body,image_bytes()),range(2))),[2,2])
        def conflict(color):
            try:return self.perform(ProductCommand(expected_version=2,reason=color),image_bytes(color))
            except HTTPException as error:return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sorted(pool.map(conflict,['blue','green'])),[3,409])
        with self.sessions() as db:
            self.assertTrue(media.read(db,db.get(User,self.actor),self.pid,self.storage.name).is_file())
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id==str(self.pid))),2)
        with self.assertRaises(IntegrityError):
            with self.sessions.begin() as db:db.get(Product,self.pid).local_photo_hash='../../file';db.flush()
        # A separate backend interpreter reads the committed pointer and disk blob.
        import subprocess, sys
        code = """from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.user import User
from app.product_knowledge.media import read
from uuid import UUID
import sys
with Session(create_engine(settings.database_url)) as db:
 assert read(db, db.get(User, int(sys.argv[1])), UUID(sys.argv[2]), sys.argv[3]).is_file()
print('Independent backend process: PASS')
"""
        result=subprocess.run([sys.executable,'-c',code,str(self.actor),str(self.pid),self.storage.name],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        body=ProductCommand(expected_version=3,reason='delete')
        self.assertEqual(self.perform(body,None),4);self.assertEqual(self.perform(body,None),4)

    def test_downgrade_retains_photo_action_history(self):
        self.perform(ProductCommand(expected_version=1,reason='history'),image_bytes())
        self.perform(ProductCommand(expected_version=2,reason='delete'),None)
        from alembic import command
        from alembic.config import Config
        with self.assertRaisesRegex(RuntimeError,'PRODUCT_PHOTO_HISTORY_EXISTS'):
            command.downgrade(Config('alembic.ini'),'20261009_0076')
