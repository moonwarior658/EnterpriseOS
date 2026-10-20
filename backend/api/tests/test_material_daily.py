import asyncio,unittest
from uuid import uuid4
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from sqlalchemy import select,func
from app.core.config import settings
from app.schemas.automation import validate_automation_schedule_contract,DailyScheduleConfig
from app.automation.catalog import get_automation_type
from app.raw_materials import daily,purchase_refresh
from app.models.automation import AutomationExecution as Execution
from app.automation.dispatch import create_automation_execution
from app.automation.local_actions import LocalAutomationActionExecutor
from app.automation.outbox import SqlAlchemyOutboxStore,OutboxClaimLostError
from tests import test_material_purchases as fixture

class DailyContractTests(unittest.TestCase):
    def test_disabled_by_default_and_bounded_to_explicit_cards(self):
        self.assertFalse(settings.raw_material_daily_accepted)
        self.assertFalse(get_automation_type(daily.ACTION).is_available)
        payload=dict(product_ids=[str(uuid4())])
        with self.assertRaises(ValueError):validate_automation_schedule_contract(daily.ACTION,DailyScheduleConfig(type='daily',time='06:00'),payload)
        for ids in ([],[str(uuid4())]*2,[str(uuid4()) for _ in range(11)]):
            with self.assertRaises(ValueError):daily.DailyPayload(product_ids=ids)
        with patch.object(settings,'raw_material_daily_accepted',True):
            self.assertTrue(get_automation_type(daily.ACTION).is_available)
            self.assertEqual(validate_automation_schedule_contract(daily.ACTION,DailyScheduleConfig(type='daily',time='06:00'),payload),payload)

class DailyCoreTests(unittest.TestCase):
    seed=fixture.PurchaseFlowTests.seed
    bind_client=fixture.PurchaseFlowTests.bind_client
    enroll=fixture.PurchaseFlowTests.enroll
    role=fixture.PurchaseFlowTests.role
    tearDown=fixture.PurchaseFlowTests.tearDown
    setUp=fixture.PurchaseFlowTests.setUp
    def test_existing_core_parent_queues_one_child_and_terminal_replay_is_rejected(self):
        with self.sessions.begin() as db:
            parent=create_automation_execution(db,automation_type=daily.ACTION,tenant_id=self.tenant,scope_type='company',scope_id=None,recipients=[],payload=dict(product_ids=[str(self.product)]))
            parent_id=parent.execution_id
        store=SqlAlchemyOutboxStore(self.sessions);now=datetime.now(timezone.utc)+timedelta(seconds=1)
        claim=store.claim_next(worker_id='daily-test',claimed_at=now)
        self.assertEqual(claim.execution_id,parent_id)
        with patch.object(settings,'raw_material_daily_accepted',True):
            result=LocalAutomationActionExecutor(self.sessions).execute(claim,executed_at=now)
        self.assertEqual(result['queued'],1)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Execution).where(Execution.automation_type==purchase_refresh.ACTION)),1)
            self.assertEqual(db.scalar(select(Execution).where(Execution.execution_id==parent_id)).status,'succeeded')
        with self.assertRaises(OutboxClaimLostError):LocalAutomationActionExecutor(self.sessions).execute(claim,executed_at=now)
