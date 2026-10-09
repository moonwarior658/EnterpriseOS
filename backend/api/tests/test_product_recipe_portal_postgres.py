"""K5D transactional concurrency on the dedicated disposable K5B PostgreSQL."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4
from sqlalchemy import select, func
from fastapi import HTTPException
from app.models.user import User
from app.models.audit import AuditEvent
from app.models.automation import AutomationExecution, OutboxEvent
from app.models.product_recipe import ProductRecipeObservation as Observation
from app.product_knowledge import recipe_portal as portal
from app.product_knowledge.recipes import publish_recipes
from app.schemas.product_recipes import RecipeConfirmation, RecipePortalRefresh
from tests import test_product_recipes_postgres as k5b


@unittest.skipUnless(k5b.URL, 'K5B_TEST_DATABASE_URL not configured')
class RecipePortalPostgresTests(unittest.TestCase):
    tearDown = k5b.RecipePostgresTests.tearDown

    def setUp(self):
        k5b.RecipePostgresTests.setUp(self)
        with self.sessions.begin() as db:publish_recipes(db,self.tenant,self.collected,execution_id=uuid4())
        with self.sessions() as db:
            row=db.scalar(select(Observation).where(Observation.tenant_id==self.tenant))
            self.product=row.product_id
            self.confirmation=RecipeConfirmation(observation_id=row.id,manifest_hash=row.payload['manifest_hash'],office_evidence='Independent Office fixture review')
            self.refresh_command=RecipePortalRefresh(context_key=portal.context_key(row.payload),effective_on='2026-10-09',request_id=uuid4())

    def confirm(self):
        with self.sessions.begin() as db:return portal.confirm(db,db.get(User,self.actor),self.product,self.confirmation).id

    def refresh(self):
        with self.sessions.begin() as db:return portal.refresh(db,db.get(User,self.actor),self.product,self.refresh_command)

    def test_concurrent_confirm_and_refresh_are_idempotent(self):
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.confirm(),range(2)))
        self.assertEqual(results[0],results[1])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id==self.tenant,AuditEvent.event_type=='PRODUCT_RECIPE_CONFIRMED')),1)
            original=copy.deepcopy(db.get(Observation,self.confirmation.observation_id).payload)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.refresh(),range(2)))
        self.assertEqual(results[0],results[1])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AutomationExecution).where(AutomationExecution.tenant_id==self.tenant)),1)
            execution=db.scalar(select(AutomationExecution).where(AutomationExecution.tenant_id==self.tenant))
            self.assertEqual(db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.execution_id==execution.execution_id)),1)
            self.assertEqual(db.get(Observation,self.confirmation.observation_id).payload,original)

    def test_publication_wins_source_lock_and_stale_confirmation_is_rejected(self):
        waiting=Event()
        def confirm_waiting():
            waiting.set()
            return self.confirm()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.sessions.begin() as db:
                product=portal.find_product(db,db.get(User,self.actor),self.product)
                portal.lock_source(db,db.get(User,self.actor),product)
                future=pool.submit(confirm_waiting)
                self.assertTrue(waiting.wait(3))
                changed=copy.deepcopy(self.collected);changed['observed_at']+=timedelta(seconds=1)
                root=next(iter(changed['bundles']))
                # One shared chart object occurs in tree/assembled/history fixture.
                changed['bundles'][root]['assembled']['assemblyCharts'][0]['items'][0]['amountIn']='0.050000000000000001'
                publish_recipes(db,self.tenant,changed,execution_id=uuid4())
            with self.assertRaises(HTTPException) as error:future.result(timeout=10)
            self.assertEqual(error.exception.status_code,409)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id==self.tenant,AuditEvent.event_type=='PRODUCT_RECIPE_CONFIRMED')),0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Observation).where(Observation.tenant_id==self.tenant)),2)
