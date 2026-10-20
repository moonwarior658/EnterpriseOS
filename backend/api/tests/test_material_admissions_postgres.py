"""Actual PG constraints, locking, transaction atomicity and irreversible history guard."""
import os, unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from app.automation.outbox import SqlAlchemyOutboxStore
from app.models.automation import AutomationExecution, OutboxEvent
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import select, text, func
from sqlalchemy.exc import DBAPIError
from app.models.raw_material import MaterialDocumentAdmission as Decision
from app.models.user import User
from app.models.iiko import IikoUnitMapping
from app.raw_materials import admissions
from tests import test_material_admissions as flow
from tests import test_material_purchases_postgres as pg
from tests import test_raw_materials_postgres as fixture

@unittest.skipUnless(os.getenv('RAW_MATERIAL_TEST_DATABASE_URL'),'Isolated PostgreSQL not configured')
class AdmissionPostgresTests(flow.AdmissionFlowTests):
    setUpClass=classmethod(fixture.RawMaterialPostgresTests.setUpClass.__func__)
    def setUp(self):
        pg.PurchasePostgresTests.setUp(self)
        self.path='/raw-materials/'+str(self.product)
        with self.sessions() as db:self.source_unit=db.scalar(select(IikoUnitMapping.iiko_unit_id).where(IikoUnitMapping.tenant_id==self.tenant))
    def claim(self):
        original=SqlAlchemyOutboxStore.claim_statement
        # Shared retained fixture database: only claim this test tenant's events.
        with patch.object(SqlAlchemyOutboxStore,'claim_statement',side_effect=lambda *args,**kwargs: original(*args,**kwargs).where(OutboxEvent.execution_id.in_(select(AutomationExecution.execution_id).where(AutomationExecution.tenant_id==self.tenant)))):
            return SqlAlchemyOutboxStore(self.sessions).claim_next(worker_id='admission-pg-test',claimed_at=datetime.now(timezone.utc)+timedelta(seconds=1))
    def test_concurrent_idempotent_grant_and_conflicting_revocations(self):
        self.prepare();body=self.command()
        def execute(value):
            try:
                with self.sessions.begin() as db:
                    return admissions.decide(db,db.get(User,self.actor_id),self.product,UUID(self.snapshot_id),admissions.DecisionCommand(**value))
            except HTTPException as error:return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,[body,body]))
        self.assertEqual(results[0]['id'],results[1]['id'])
        commands=[self.command(action='REVOKE',expected_revision=1) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,commands))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1);self.assertIn(409,results)
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Decision).where(Decision.tenant_id==self.tenant)),2)
    def test_database_immutable_history_tenant_actor_scope_and_constraints(self):
        self.prepare();r=self.post();self.assertEqual(r.status_code,200,r.text);row_id=UUID(r.json()['id'])
        for sql in ('UPDATE material_document_admissions SET comment=comment WHERE id=:id','DELETE FROM material_document_admissions WHERE id=:id'):
            with self.assertRaisesRegex(DBAPIError,'MATERIAL_HISTORY_IMMUTABLE'):
                with self.engine.begin() as connection:connection.execute(text(sql),dict(id=row_id))
        with self.sessions() as db:
            row=db.get(Decision,row_id);fields={c.name:getattr(row,c.name) for c in Decision.__table__.columns}
        for changes in (dict(tenant_id='foreign'),dict(product_id=self.second),dict(actor_user_id=99999999),dict(source_id='bad'),dict(evidence=''),dict(kind='BASE_UNIT_CONTAINER',line_num=''),dict(revision=3),dict(action='GRANT')):
            with self.assertRaises(DBAPIError,msg=str(changes)):
                with self.sessions.begin() as db:
                    db.add(Decision(**{**fields,'id':uuid4(),'request_id':uuid4(),'action':'REVOKE','revision':2,**changes}));db.flush()
        from alembic import command
        from alembic.config import Config
        with fixture.migration_settings(self.url):
            with self.assertRaisesRegex(RuntimeError,'MATERIAL_ADMISSION_HISTORY_EXISTS'):command.downgrade(Config('alembic.ini'),'20261020_0082')
        with self.engine.connect() as conn:self.assertEqual(conn.execute(text('select version_num from alembic_version')).scalar(),'20261020_0083')
