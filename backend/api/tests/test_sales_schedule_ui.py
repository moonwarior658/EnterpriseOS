"""UI-shaped sales schedule resolves its source before scheduler/outbox dispatch."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, MetaData, JSON, Integer, BigInteger, event, inspect
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.dialects.postgresql import JSONB

from tests import test_sales_foundation as fixtures
from app.api.dependencies import get_current_admin
from app.api.routes.automation import router
from app.db.session import get_db
from app.models.user import User
from app.models.sales import SalesSyncState, SalesDaySync
from app.models.automation import AutomationSchedule, AutomationScheduleAuditEvent, AutomationExecution, OutboxEvent
from app.automation.scheduler import run_scheduler_once
from app.automation.outbox import SqlAlchemyOutboxStore, OutboxWorker, DeliveryStatus
from app.automation.local_actions import LocalAutomationActionExecutor
from app.integrations.iiko.config import IikoSettings
from app.sales.sync import source_identity
from app.schemas.automation import SalesSyncPayload
from pydantic import ValidationError


class SalesScheduleUiTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.SalesFoundationTests.setUp
    tearDown = fixtures.SalesFoundationTests.tearDown

    def client(self):
        # Local SQLite copies only; production metadata and PostgreSQL defaults
        # stay untouched. JSONB/BigInteger use their SQLite storage equivalents.
        metadata = MetaData()
        User.__table__.to_metadata(metadata)
        for model in (AutomationSchedule, AutomationScheduleAuditEvent, AutomationExecution, OutboxEvent):
            table = model.__table__.to_metadata(metadata)
            for column in table.columns:
                if isinstance(column.type, JSONB):
                    column.type = JSON(); column.server_default = None
                if column.primary_key and isinstance(column.type, BigInteger): column.type = Integer()
            table.create(self.engine, checkfirst=True)
        def restore_sqlite_timezone(session, instance):
            if isinstance(instance, (AutomationSchedule, AutomationExecution, OutboxEvent)):
                for field in inspect(instance).mapper.column_attrs:
                    value = getattr(instance, field.key)
                    if isinstance(value, datetime) and value.tzinfo is None:
                        set_committed_value(instance, field.key, value.replace(tzinfo=timezone.utc))
        event.listen(self.sessions, 'loaded_as_persistent', restore_sqlite_timezone)
        app = FastAPI(); app.include_router(router)
        def db():
            with self.sessions() as session: yield session
        def actor():
            with self.sessions() as session: return session.get(User, 1)
        app.dependency_overrides[get_db] = db
        app.dependency_overrides[get_current_admin] = actor
        return TestClient(app)

    def body(self, **changes):
        return dict(name='Обновление продаж', automation_type='sales.sync_iiko', scope_type='company',
            scope_id=None, schedule_config={'type':'interval','minutes':15}, payload={}, recipients=[],
            timezone='Asia/Yekaterinburg', is_enabled=True, **changes)

    async def test_ui_create_scheduler_recurs_and_worker_backfills(self):
        settings = IikoSettings(enabled=True, base_url='https://example.invalid/resto/', login='test', password='test')
        sid = source_identity(settings)
        with self.sessions.begin() as db:
            db.get(SalesSyncState, ('eclair', self.source_id)).source_id = sid
        with self.client() as client:
            response = client.post('/automation/schedules', json=self.body())
            self.assertEqual(response.status_code, 201, response.text)
            schedule_id = response.json()['id']
            self.assertEqual(response.json()['payload'], {'source_id':sid})
            self.assertEqual(client.patch('/automation/schedules/' + str(schedule_id), json={'payload':{}}).status_code, 200)
        with self.sessions() as db:
            scheduled = db.get(AutomationSchedule, schedule_id).next_run_at.replace(tzinfo=fixtures.timezone.utc)
        provider = AsyncMock()
        iiko = AsyncMock(); iiko.__aenter__.return_value = iiko; iiko.get_sales_olap.return_value = []
        worker = OutboxWorker(store=SqlAlchemyOutboxStore(self.sessions), provider=provider, worker_id='sales-test',
            callback_url='http://unused.invalid', local_executor=LocalAutomationActionExecutor(self.sessions))
        with patch('app.sales.sync.get_iiko_settings', return_value=settings), patch('app.sales.sync.IikoServerClient', return_value=iiko):
            self.assertEqual(run_scheduler_once(self.sessions, now=scheduled).created, 1)
            self.assertEqual((await worker.process_one()).status, DeliveryStatus.PUBLISHED)
            with self.sessions() as db:
                state = db.get(SalesSyncState, ('eclair', sid))
                self.assertIsNotNone(state.last_success_at)
                self.assertIsNone(state.error_code)
                days = list(db.scalars(select(SalesDaySync.business_date)))
                self.assertGreater(len(days), 30)
                self.assertEqual(db.get(AutomationSchedule, schedule_id).next_run_at.replace(tzinfo=fixtures.timezone.utc), scheduled + timedelta(minutes=15))
            self.assertEqual(run_scheduler_once(self.sessions, now=scheduled + timedelta(minutes=14)).created, 0)
            self.assertEqual(run_scheduler_once(self.sessions, now=scheduled + timedelta(minutes=15)).created, 1)
            self.assertEqual((await worker.process_one()).status, DeliveryStatus.PUBLISHED)
            provider.send_command.assert_not_called()
            with self.sessions() as db:
                self.assertGreater(len(list(db.scalars(select(SalesDaySync.business_date)))), len(days))

    def test_missing_ambiguous_foreign_source_and_bad_schedule_fail_closed(self):
        with self.client() as client:
            for body in [dict(self.body(), payload={'source_id':'b'*64}),
                         dict(self.body(), schedule_config={'type':'interval','minutes':10}),
                         dict(self.body(), scope_type='department', scope_id='point')]:
                self.assertEqual(client.post('/automation/schedules', json=body).status_code, 422)
            with self.sessions.begin() as db:
                db.add(SalesSyncState(tenant_id='eclair', source_id='b'*64, source_timezone='Asia/Yekaterinburg',
                    history_from=fixtures.DAY, backfill_next=fixtures.DAY))
            response = client.post('/automation/schedules', json=self.body())
            self.assertEqual(response.status_code, 422)
            self.assertIn('не настроен однозначно', response.json()['detail'])
            with self.sessions.begin() as db:
                for state in db.scalars(select(SalesSyncState)): state.tenant_id = 'another-company'
            self.assertEqual(client.post('/automation/schedules', json=self.body()).status_code, 422)
        with self.assertRaises(ValidationError): SalesSyncPayload.model_validate({})
