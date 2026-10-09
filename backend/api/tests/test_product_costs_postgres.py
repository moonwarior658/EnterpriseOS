"""Only dedicated disposable localhost K5C PostgreSQL; never production."""
import asyncio
import os
os.environ.setdefault("POSTGRES_DB","test");os.environ.setdefault("POSTGRES_USER","test")
os.environ.setdefault("POSTGRES_PASSWORD","test");os.environ.setdefault("JWT_SECRET_KEY","test-jwt-secret")
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4, UUID
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from alembic import command
from alembic.config import Config
from app.core.config import settings
from app.models.product_cost import ProductCostObservation as Observation, ProductCostVerification as Verification
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from app.models.automation import AutomationExecution, ExecutionStatus, OutboxEvent, OutboxStatus
from app.models.user import User
from app.product_knowledge.costs import CostRefreshPayload, scope, enqueue, publish_costs, require_verified_schedule
from app.product_knowledge.cost_portal import CostConfirmation, confirm
from app.automation.local_actions import LocalAutomationActionExecutor
from app.automation.outbox import ClaimedOutboxEvent, OutboxClaimLostError
from tests.test_product_costs import fixture
from tests import test_product_knowledge_postgres as k1
URL=os.getenv('K5C_TEST_DATABASE_URL')

@unittest.skipUnless(URL,'K5C_TEST_DATABASE_URL not configured')
class CostPostgresTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy.engine import make_url
        url=make_url(URL)
        if url.host!='127.0.0.1' or url.database!='eos_supply_migration_test' or url.port!=55439:
            raise RuntimeError('Dedicated disposable K5C database required')
        with patch.object(k1,'URL',URL):k1.ProductKnowledgePostgresTests.setUp(self)
        k1.ProductKnowledgePostgresTests.load(self)
        root=str(self.snapshot.products[0].id);self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.policy=CostRefreshPayload(source_id=self.source,product_ids=[root],warehouse_ids=[],context_label='Fixture explicit Office context',scope_evidence='Explicit synthetic stock aggregation and Office comparison')
        with self.sessions() as db:
            products=scope(db,self.tenant,self.policy);p=db.get(Product,UUID(products[root]));self.local=p.id;self.root=fixture(root,str(p.unit_id))
        self.collected=dict(products=products,roots={root:self.root},scope=self.policy.model_dump(mode='json'),stock_at=self.now,observed_at=self.now)
    tearDown=k1.ProductKnowledgePostgresTests.tearDown
    def apply(self,execution):
        with self.sessions.begin() as db:return publish_costs(db,self.tenant,self.collected,execution_id=execution)
    def test_concurrent_publication_immutable_history_and_downgrade_guard(self):
        execution=uuid4()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.apply(execution),range(2)))
        self.assertEqual(results[0],results[1])
        with self.sessions() as db:
            rows=list(db.scalars(select(Observation).where(Observation.tenant_id==self.tenant)));self.assertEqual(len(rows),1);row=rows[0]
        for statement in ("UPDATE product_cost_observations SET status='INCOMPLETE' WHERE id=:id",'DELETE FROM product_cost_observations WHERE id=:id'):
            with self.assertRaises(DBAPIError):
                with self.engine.begin() as c:c.execute(text(statement),dict(id=row.id))
        from sqlalchemy.engine import make_url
        url=make_url(URL);previous=(settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port)
        try:
            settings.postgres_db=url.database;settings.postgres_user=url.username;settings.postgres_password=url.password or '';settings.postgres_host=url.host;settings.postgres_port=url.port
            with self.assertRaisesRegex(RuntimeError,'COST_HISTORY_EXISTS'):command.downgrade(Config('alembic.ini'),'20261009_0078')
            with self.engine.connect() as c:self.assertEqual(c.execute(text('select version_num from alembic_version')).scalar(),'20261009_0079')
        finally:settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port=previous
    def test_confirmation_schedule_gate_and_immutable_verification(self):
        self.apply(uuid4())
        with self.sessions.begin() as db:
            with self.assertRaises(ValueError):require_verified_schedule(db,self.tenant,self.policy)
            row=db.scalar(select(Observation).where(Observation.tenant_id==self.tenant))
            v=confirm(db,db.get(User,self.actor),self.local,CostConfirmation(observation_id=row.id,content_hash=row.content_hash,office_ssn='0.25',estimated=False,warehouse_confirmed=True,context_confirmed=True,allow_updates=True,office_evidence='Synthetic independent Office and warehouse context verification'),now=self.now)
            vid=v.id;require_verified_schedule(db,self.tenant,self.policy)
        for statement in ("UPDATE product_cost_verifications SET payload='{}' WHERE id=:id",'DELETE FROM product_cost_verifications WHERE id=:id'):
            with self.assertRaises(DBAPIError):
                with self.engine.begin() as c:c.execute(text(statement),dict(id=vid))
    def test_worker_atomic_commit_replay_and_terminal_lease_guard(self):
        with self.sessions.begin() as db:
            execution=enqueue(db,db.get(User,self.actor),self.policy);execution_id=execution.execution_id
            event=db.scalar(select(OutboxEvent).where(OutboxEvent.execution_id==execution_id));event.status=OutboxStatus.PROCESSING;event.locked_by='k5c-worker';event.locked_at=self.now
            event.attempt_count=1;db.flush()
            claim=ClaimedOutboxEvent(id=event.id,event_id=event.event_id,execution_id=execution_id,contract_version=event.contract_version,
                automation_type='products.sync_iiko_costs',tenant_id=self.tenant,requested_at=self.now,payload=self.policy.model_dump(mode='json'),attempt_count=1,max_attempts=3,lock_token='k5c-worker')
        executor=LocalAutomationActionExecutor(self.sessions)
        with patch('app.product_knowledge.costs.collect_costs',new=AsyncMock(return_value=self.collected)):
            result=asyncio.run(executor.execute(claim,executed_at=self.now));self.assertEqual(result['counts']['UNVERIFIED'],1)
            with self.assertRaises(OutboxClaimLostError):asyncio.run(executor.execute(claim,executed_at=self.now))
        with self.sessions() as db:
            execution=db.scalar(select(AutomationExecution).where(AutomationExecution.execution_id==execution_id));self.assertEqual(execution.status,ExecutionStatus.SUCCEEDED)
            row=db.scalar(select(Observation).where(Observation.tenant_id==self.tenant));self.assertEqual(row.execution_id,execution_id)
