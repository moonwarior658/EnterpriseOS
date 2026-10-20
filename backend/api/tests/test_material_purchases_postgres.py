"""Dedicated disposable PG: concurrent commands, publication and database history guards."""
import os,unittest
os.environ.setdefault('POSTGRES_DB','test')
os.environ.setdefault('POSTGRES_USER','test')
os.environ.setdefault('POSTGRES_PASSWORD','test')
os.environ.setdefault('JWT_SECRET_KEY','test-jwt-secret')
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import select,func,text
from sqlalchemy.exc import DBAPIError
from app.models.user import User
from app.models.iiko import IikoProductMapping,IikoUnitMapping
from app.models.automation import AutomationExecution as Execution
from app.models.raw_material import MaterialPurchaseSnapshot as Snapshot
from app.raw_materials import purchase_refresh as refresh
from app.raw_materials.purchases import evaluate,SOURCE
from tests import test_raw_materials_postgres as fixture
from tests.test_material_purchases import document,SUPPLIERS

@unittest.skipUnless(os.getenv('RAW_MATERIAL_TEST_DATABASE_URL'),'Disposable PG not configured')
class PurchasePostgresTests(unittest.TestCase):
    setUpClass=classmethod(fixture.RawMaterialPostgresTests.setUpClass.__func__)
    tearDown=fixture.RawMaterialPostgresTests.tearDown
    enroll=fixture.RawMaterialPostgresTests.enroll
    def setUp(self):
        fixture.RawMaterialPostgresTests.setUp(self);self.enroll()
        with self.sessions.begin() as db:
            unit=db.scalar(select(IikoUnitMapping).where(IikoUnitMapping.tenant_id==self.tenant));self.source_product=uuid4()
            db.add(IikoProductMapping(tenant_id=self.tenant,iiko_product_id=self.source_product,eos_product_id=self.product,status='CONFIRMED',source_name='PG fixture',source_unit_id=unit.iiko_unit_id,is_deleted=False))
    def enqueue(self,request_id):
        with self.sessions.begin() as db:return refresh.refresh(db,db.get(User,self.actor_id),self.product,refresh.RefreshCommand(request_id=request_id))
    def snapshot(self):
        with self.sessions() as db:
            execution=db.scalar(refresh.attempts(db,self.tenant,self.product).limit(1));payload=execution.payload
        result=evaluate([document(str(self.source_product),payload['mapping']['unit_id'])],SUPPLIERS,payload['mapping'],date_from='2026-04-01',date_to='2026-10-21')
        return execution.execution_id,dict(product_id=str(self.product),source_id=SOURCE,mapping=payload['mapping'],policy='fixture',observed_at=datetime.now(timezone.utc).isoformat(),manifest=[],result=result)
    def test_concurrent_command_and_publication_exactly_once(self):
        request_id=uuid4()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(self.enqueue,[request_id,request_id]))
        self.assertEqual(results[0]['status'],results[1]['status'])
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(self.enqueue,[uuid4(),uuid4()]))
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Execution).where(Execution.tenant_id==self.tenant)),1)
        execution_id,snapshot=self.snapshot()
        def publish(_):
            with self.sessions.begin() as db:return refresh.publish(db,self.tenant,snapshot,execution_id=execution_id)
        with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(publish,range(2)))
        self.assertEqual(rows[0]['snapshot_id'],rows[1]['snapshot_id'])
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.tenant_id==self.tenant)),1)
    def test_immutable_tenant_execution_and_status_amount_constraints(self):
        self.enqueue(uuid4());execution_id,snapshot=self.snapshot()
        with self.sessions.begin() as db:row=refresh.publish(db,self.tenant,snapshot,execution_id=execution_id)
        for sql in ['UPDATE material_purchase_snapshots SET amount = NULL WHERE id=:id','DELETE FROM material_purchase_snapshots WHERE id=:id']:
            with self.assertRaisesRegex(DBAPIError,'MATERIAL_HISTORY_IMMUTABLE'):
                with self.engine.begin() as connection:connection.execute(text(sql),dict(id=row['snapshot_id']))
        with self.sessions() as db:
            actual=db.scalar(select(Snapshot).where(Snapshot.id==row['snapshot_id']))
            fields={c.name:getattr(actual,c.name) for c in Snapshot.__table__.columns}
        for changes in [dict(tenant_id='other'),dict(status='READY',amount=None),dict(status='BLOCKED',amount='12'),dict(execution_id=uuid4())]:
            with self.assertRaises(DBAPIError):
                with self.sessions.begin() as db:db.add(Snapshot(**{**fields,'id':uuid4(),**changes}));db.flush()
        with self.engine.begin() as connection:
            with self.assertRaisesRegex(DBAPIError,'MATERIAL_PURCHASE_EXECUTION_SCOPE'):
                # An existing execution of a different tenant/product must also fail.
                connection.execute(text("INSERT INTO material_purchase_snapshots (id,tenant_id,product_id,execution_id,source_id,status,amount,content_hash,observed_at,payload) SELECT :newid,'foreign',product_id,execution_id,source_id,status,amount,content_hash,observed_at,payload FROM material_purchase_snapshots WHERE id=:id"),dict(newid=str(uuid4()),id=row['snapshot_id']))

    def test_rollback_on_audit_failure_and_populated_downgrade_guard(self):
        from unittest.mock import patch
        from alembic import command
        from alembic.config import Config
        with patch.object(refresh,'record_audit_event',side_effect=RuntimeError('Injected audit failure')):
            with self.assertRaises(RuntimeError):self.enqueue(uuid4())
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Execution).where(Execution.tenant_id==self.tenant)),0)
        self.enqueue(uuid4());execution_id,snapshot=self.snapshot()
        with patch.object(refresh,'record_audit_event',side_effect=RuntimeError('Injected audit failure')):
            with self.assertRaises(RuntimeError):
                with self.sessions.begin() as db:refresh.publish(db,self.tenant,snapshot,execution_id=execution_id)
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.tenant_id==self.tenant)),0)
        with self.sessions.begin() as db:refresh.publish(db,self.tenant,snapshot,execution_id=execution_id)
        with fixture.migration_settings(self.url):
            with self.assertRaisesRegex(RuntimeError,'MATERIAL_(ADMISSION|STANDARD|PURCHASE)_HISTORY_EXISTS'):command.downgrade(Config('alembic.ini'),'20261020_0080')
        with self.engine.connect() as connection:self.assertEqual(connection.execute(text('SELECT version_num FROM alembic_version')).scalar(),'20261020_0083')
