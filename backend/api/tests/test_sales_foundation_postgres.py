"""Run only against a newly created, fully migrated disposable sales database."""
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.automation.local_actions import LocalAutomationActionExecutor
from app.automation.outbox import OutboxWorker, SqlAlchemyOutboxStore, DeliveryStatus
from app.automation.scheduler import run_scheduler_once
from app.integrations.iiko.config import IikoSettings
from app.models.automation import AutomationExecution, ExecutionStatus, AutomationSchedule
from app.models.employee import Employee, EmployeeRole, EmployeeRoleAssignment, IikoDepartmentMapping, IikoEmployeeLink
from app.models.sales import SalesFact, SalesSyncState
from app.models.supply import Department, DepartmentBusinessType
from app.models.user import User
from app.sales.configure import configure_source
from app.sales.service import daily_query, ingest_day, reconcile

URL = os.getenv("SALES_TEST_DATABASE_URL")


@unittest.skipUnless(URL, "SALES_TEST_DATABASE_URL not configured")
class SalesPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_outbox_sync_numeric_constraints_and_idempotency(self):
        url = make_url(URL)
        self.assertEqual(url.database, "eos_sales_foundation_test")
        self.assertIn(url.host, ("localhost", "127.0.0.1"))
        engine = create_engine(URL)
        sessions = sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        day = now.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Yekaterinburg')).date()
        tenant = 'sales-test-' + uuid4().hex[:16]
        point, department_id, employee_id, order, item, product = [uuid4() for _ in range(6)]
        settings = IikoSettings(enabled=True, base_url="https://sales.test.invalid/resto", login="test", password="test")
        with sessions.begin() as db:
            self.assertEqual(db.scalar(text('select version_num from alembic_version')), "20261006_0070")
            actor = User(username=tenant, display_name="Test", hashed_password="test", tenant_id=tenant, is_active=True, is_admin=True)
            db.add(actor); db.flush()
            db.add(Department(id=department_id, tenant_id=tenant, code="TEST", name="Test", business_type=DepartmentBusinessType.RETAIL_POINT))
            employee = Employee(id=employee_id, tenant_id=tenant, linked_user_id=actor.id,
                full_name="Test", birth_date=date(1990,1,1), phone="0", residence_address="Test")
            db.add(employee); db.flush()
            db.add(EmployeeRoleAssignment(tenant_id=tenant, employee_id=employee_id, role=EmployeeRole.ADMIN,
                valid_from=now-timedelta(days=3), reason="test", assigned_by_user_id=actor.id))
            db.add(IikoDepartmentMapping(tenant_id=tenant, iiko_department_id=uuid4(), olap_department_id=point,
                eos_department_id=department_id, reason="explicit", decided_by_user_id=actor.id))
            db.add(IikoEmployeeLink(tenant_id=tenant, employee_id=employee_id, iiko_user_id="cashier", iiko_display_name="Test",
                valid_from=now-timedelta(days=3), reason="test", created_by_user_id=actor.id))
        with patch('app.sales.configure.get_iiko_settings', return_value=settings):
            with sessions.begin() as db:
                state = configure_source(db, actor=db.get(User, actor.id), source_timezone="Asia/Yekaterinburg", history_from=day)
                source_id = state.source_id
            with sessions.begin() as db:
                configure_source(db, actor=db.get(User, actor.id), source_timezone="Asia/Yekaterinburg", history_from=day)
                self.assertEqual(len(db.scalars(select(AutomationSchedule).where(AutomationSchedule.tenant_id==tenant)).all()), 1)
        row = {"Department.Id":str(point), "UniqOrderId.Id":str(order), "ItemSaleEvent.Id":str(item), "DishId":str(product),
            "OpenDate.Typed":str(day), "OpenTime":str(day)+"T10:00:00", "Cashier.Id":"cashier",
            "DishAmountInt":Decimal('1.123456789123456789'), "DishSumInt":Decimal('20.123456789123456789'),
            "DishDiscountSumInt":Decimal('20.123456789123456789'), "DishReturnSum":0,
            "Storned":"FALSE", "OrderDeleted":"NOT_DELETED", "DeletedWithWriteoff":"NOT_DELETED"}
        client = AsyncMock(); client.__aenter__.return_value = client; client.get_sales_olap.return_value=[row]
        provider = AsyncMock()
        worker = OutboxWorker(store=SqlAlchemyOutboxStore(sessions), provider=provider, worker_id="sales-test",
            callback_url="http://unused.invalid", local_executor=LocalAutomationActionExecutor(sessions))
        with patch('app.sales.sync.get_iiko_settings', return_value=settings), patch('app.sales.sync.IikoServerClient', return_value=client):
            result = run_scheduler_once(sessions, now=datetime.now(timezone.utc))
            self.assertEqual(result.created, 1)
            result = await worker.process_one()
            self.assertEqual(result.status, DeliveryStatus.PUBLISHED)
            provider.send_command.assert_not_called()
        with sessions() as db:
            fact = db.scalar(select(SalesFact).where(SalesFact.tenant_id==tenant))
            self.assertEqual(fact.quantity, Decimal('1.123456789123456789'))
            self.assertEqual(fact.amount_after_discount, Decimal('20.123456789123456789'))
            self.assertEqual(db.scalar(select(AutomationExecution.status).where(AutomationExecution.tenant_id==tenant)), ExecutionStatus.SUCCEEDED)
        with sessions.begin() as db:
            state = db.get(SalesSyncState, (tenant, source_id))
            ingest_day(db, [row], state=state, day=day, department_ids=[point], seen_at=now)
            self.assertEqual(len(db.scalars(select(SalesFact).where(SalesFact.tenant_id==tenant)).all()), 1)
            with self.assertRaises(Exception):
                with db.begin_nested():
                    duplicate = SalesFact(**{c.name:getattr(fact,c.name) for c in SalesFact.__table__.columns if c.name!='id'})
                    db.add(duplicate); db.flush()
            with self.assertRaises(Exception):
                with db.begin_nested():
                    fact = db.scalar(select(SalesFact).where(SalesFact.tenant_id==tenant))
                    fact.employee_id = uuid4(); db.flush()
        engine.dispose()
