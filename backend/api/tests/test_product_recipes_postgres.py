"""Only a dedicated disposable localhost K5B database; no production access."""
import asyncio
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from alembic import command
from alembic.config import Config
os.environ.setdefault('POSTGRES_DB','test')
os.environ.setdefault('POSTGRES_USER','test')
os.environ.setdefault('POSTGRES_PASSWORD','test')
os.environ.setdefault('JWT_SECRET_KEY','test-jwt-secret')
from app.core.config import settings
from app.models.product_recipe import ProductRecipeVersion as Version, ProductRecipeObservation as Observation
from app.models.automation import AutomationExecution, ExecutionStatus, OutboxEvent, OutboxStatus
from app.models.user import User
from app.product_knowledge.recipes import RecipeRefreshPayload, scope, enqueue, publish_recipes
from app.automation.local_actions import LocalAutomationActionExecutor
from app.automation.outbox import ClaimedOutboxEvent, OutboxClaimLostError
from tests.test_product_recipes import fixture
from tests import test_product_knowledge_postgres as k1
URL=os.getenv('K5B_TEST_DATABASE_URL')

@unittest.skipUnless(URL,'K5B_TEST_DATABASE_URL not configured')
class RecipePostgresTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy.engine import make_url
        url=make_url(URL)
        if url.host!='127.0.0.1' or url.database!='eos_supply_migration_test' or url.port!=55439:
            raise RuntimeError('Dedicated disposable K5B database required')
        with patch.object(k1,'URL',URL):k1.ProductKnowledgePostgresTests.setUp(self)
        k1.ProductKnowledgePostgresTests.load(self)
        root=str(self.snapshot.products[0].id)
        _,_,bundle,refs=fixture(root)
        self.policy=RecipeRefreshPayload(source_id=self.source,product_ids=[root],department_id=uuid4(),effective_on='2026-10-09',scope_evidence='Explicit synthetic K5B scope')
        with self.sessions() as db:
            from app.models.product_knowledge import ProductKnowledgeProduct
            from uuid import UUID
            products=scope(db,self.tenant,self.policy)
            product=db.get(ProductKnowledgeProduct,UUID(products[root]));unit=str(product.unit_id)
            refs['products'][root]['mainUnit']=unit;refs['units'][unit]=dict(id=unit,name=product.unit_name)
        self.collected=dict(products=products,bundles={root:bundle},references=refs,scope=self.policy.model_dump(mode='json'),observed_at=datetime.now(timezone.utc))
    tearDown=k1.ProductKnowledgePostgresTests.tearDown
    def publish(self,execution):
        with self.sessions.begin() as db:return publish_recipes(db,self.tenant,self.collected,execution_id=execution)
    def test_concurrent_retry_immutable_history_and_downgrade_guard(self):
        execution=uuid4()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(self.publish,[execution,execution]))
        self.assertEqual(results[0],results[1])
        with self.sessions() as db:
            version=db.scalar(select(Version).where(Version.tenant_id==self.tenant))
            observation=db.scalar(select(Observation).where(Observation.tenant_id==self.tenant))
            version_id,observation_id=version.id,observation.id
            self.assertEqual(len(list(db.scalars(select(Version).where(Version.tenant_id==self.tenant)))),4)
            self.assertEqual(len(list(db.scalars(select(Observation).where(Observation.tenant_id==self.tenant)))),1)
            self.assertTrue(any('0.00000000123456789' in str(v.payload) for v in db.scalars(select(Version).where(Version.tenant_id==self.tenant))))
        for table,identity in [('product_recipe_versions',version_id),('product_recipe_observations',observation_id)]:
            for sql in [f'UPDATE {table} SET payload=payload WHERE id=:id',f'DELETE FROM {table} WHERE id=:id']:
                with self.assertRaisesRegex(DBAPIError,'RECIPE_HISTORY_IMMUTABLE'):
                    with self.engine.begin() as conn:conn.execute(text(sql),dict(id=identity))
        previous=(settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port)
        try:
            from sqlalchemy.engine import make_url
            url=make_url(URL)
            settings.postgres_db=url.database;settings.postgres_user=url.username;settings.postgres_password=url.password or '';settings.postgres_host=url.host;settings.postgres_port=url.port
            with self.assertRaisesRegex(RuntimeError,'RECIPE_HISTORY_EXISTS'):command.downgrade(Config('alembic.ini'),'20261009_0077')
            with self.engine.connect() as conn:self.assertEqual(conn.execute(text('select version_num from alembic_version')).scalar(),'20261009_0078')
        finally:settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port=previous
    def test_manual_enqueue_worker_and_terminal_claim(self):
        now=datetime.now(timezone.utc)
        with self.sessions.begin() as db:
            execution=enqueue(db,db.get(User,self.actor),self.policy)
            execution_id=execution.execution_id
        with self.sessions.begin() as db:
            event=db.scalar(select(OutboxEvent).where(OutboxEvent.execution_id==execution_id).with_for_update())
            event.status=OutboxStatus.PROCESSING;event.locked_by='k5b-fixture';event.locked_at=now
            claim=ClaimedOutboxEvent(id=event.id,event_id=event.event_id,execution_id=execution_id,
                contract_version='1.0',automation_type=execution.automation_type,tenant_id=self.tenant,
                requested_at=execution.requested_at,payload=self.policy.model_dump(mode='json'),
                attempt_count=1,max_attempts=3,lock_token='k5b-fixture')
        executor=LocalAutomationActionExecutor(self.sessions)
        with patch('app.product_knowledge.recipes.collect_recipes',new=AsyncMock(return_value=self.collected)):
            result=asyncio.run(executor.execute(claim,executed_at=now))
            self.assertEqual(result['counts']['UNCONFIRMED'],1)
            with self.assertRaises(OutboxClaimLostError):asyncio.run(executor.execute(claim,executed_at=now))
        with self.sessions() as db:
            execution=db.scalar(select(AutomationExecution).where(AutomationExecution.execution_id==execution_id))
            self.assertEqual(execution.status,ExecutionStatus.SUCCEEDED)
            self.assertIsNone(execution.schedule_id)

    def test_operator_resolve_is_readonly_and_uses_confirmed_ids(self):
        from tests.test_k5b_pilot_tools import pilot
        from sqlalchemy.engine import make_url
        url=make_url(URL)
        previous=(settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port)
        from app.models.employee import IikoDepartmentMapping
        with self.sessions() as db:
            mapping=db.scalar(select(IikoDepartmentMapping).where(IikoDepartmentMapping.tenant_id==self.tenant))
            department_key=pilot.key(mapping.olap_department_id)
            expected_department=str(mapping.olap_department_id)
        try:
            settings.postgres_db=url.database;settings.postgres_user=url.username;settings.postgres_password=url.password or '';settings.postgres_host=url.host;settings.postgres_port=url.port
            keys=tuple(pilot.key(p.id) for p in self.snapshot.products)
            with patch.object(pilot,'TARGETS',keys),patch.object(pilot,'DEPARTMENT_KEY',department_key):
                before=pilot.read_report('resolve',None)
                after=pilot.read_report('resolve',None)
                self.assertEqual(before,after)
                self.assertEqual(before['department_id'],expected_department)
                self.assertEqual(before['head'],['20261009_0078'])
                self.assertEqual(before['recipe_schedule_count'],0)
                self.assertEqual(before['tenant_id'],self.tenant)
                with self.assertRaisesRegex(ValueError,'PREFLIGHT_HEAD_OR_OBJECT_COLLISION'):
                    pilot.read_report('preflight',None)
        finally:settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port=previous
