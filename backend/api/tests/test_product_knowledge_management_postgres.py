"""K2 real PostgreSQL row locks, idempotency, eligibility, immutable audit and downgrade guard."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError, DBAPIError
from fastapi import HTTPException
from app.models.user import User
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from app.models.audit import AuditEvent
from app.product_knowledge.management import mutate, require_production_eligible, add_product, candidates
from app.schemas.product_knowledge import ProductCommand, StatusUpdate, ManualAdd
from tests import test_product_knowledge_postgres as k1
from alembic import command
from alembic.config import Config
from app.core.config import settings
from sqlalchemy.engine import make_url
from uuid import uuid4


@unittest.skipUnless(k1.URL, 'PRODUCT_KNOWLEDGE_TEST_DATABASE_URL not configured')
class ProductKnowledgeManagementPostgresTests(unittest.TestCase):
    tearDown=k1.ProductKnowledgePostgresTests.tearDown
    load=k1.ProductKnowledgePostgresTests.load

    def setUp(self):
        k1.ProductKnowledgePostgresTests.setUp(self)
        self.load()
        with self.sessions() as db:self.pid=db.scalar(select(Product.id).where(Product.tenant_id==self.tenant))

    def perform(self, operation, body):
        with self.sessions.begin() as db:
            return mutate(db,db.get(User,self.actor),self.pid,operation,body).version

    def test_concurrent_identical_retry_then_conflicting_versions(self):
        same=StatusUpdate(expected_version=1,reason='PG same',sale_status='OFF_SALE')
        with ThreadPoolExecutor(max_workers=2) as executor:versions=list(executor.map(lambda _:self.perform('STATUS',same),range(2)))
        self.assertEqual(versions,[2,2])
        def conflicting(status):
            try:return self.perform('STATUS',StatusUpdate(expected_version=2,reason='PG '+status,sale_status=status))
            except HTTPException as error:return error.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(conflicting,['OFF_SALE','ON_SALE']))
        self.assertEqual(sorted(results),[3,409])
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id==str(self.pid))),2)

    def test_delete_restore_eligibility_constraints_and_immutable_audit(self):
        self.perform('DELETE',ProductCommand(expected_version=1,reason='PG soft delete'))
        with self.sessions() as db:
            with self.assertRaises(HTTPException):require_production_eligible(db,self.tenant,self.pid)
            self.assertTrue(db.get(Product,self.pid).published)
        self.perform('RESTORE',ProductCommand(expected_version=2,reason='PG restore'))
        with self.sessions() as db:self.assertEqual(require_production_eligible(db,self.tenant,self.pid).id,self.pid)
        with self.assertRaises(IntegrityError):
            with self.sessions.begin() as db:db.get(Product,self.pid).version=0;db.flush()
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as db:db.execute(text('UPDATE audit_events SET reason=:reason WHERE entity_id=:id'),{'reason':'tamper','id':str(self.pid)})
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as db:db.execute(text('DELETE FROM audit_events WHERE entity_id=:id'),{'id':str(self.pid)})
        url=make_url(k1.URL);previous=(settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port)
        try:
            settings.postgres_db=url.database;settings.postgres_user=url.username;settings.postgres_password=url.password or '';settings.postgres_host=url.host;settings.postgres_port=url.port
            with self.assertRaisesRegex(RuntimeError,'K2_DATA_EXISTS'):command.downgrade(Config('alembic.ini'),'20261008_0074')
        finally:settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port=previous

    def test_concurrent_manual_add_same_uuid_and_retry(self):
        snapshot=self.snapshot.model_copy(deep=True);product=snapshot.products[0].model_copy(update={'id':uuid4()});snapshot.products.append(product)
        with self.sessions() as db:row=candidates(db,db.get(User,self.actor),snapshot,q=str(product.id))[0]
        body=ManualAdd(**{k:row[k] for k in ('source_id','iiko_product_id','confirmation_hash')},sale_status='OFF_SALE',reason='PG UUID')
        def add(_):
            with self.sessions.begin() as db:return add_product(db,db.get(User,self.actor),body,snapshot).id
        with ThreadPoolExecutor(max_workers=2) as executor:ids=list(executor.map(add,range(2)))
        self.assertEqual(ids[0],ids[1])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Product).where(Product.tenant_id==self.tenant)),3)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id==str(ids[0]))),1)
