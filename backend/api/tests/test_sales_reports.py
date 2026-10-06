"""A5 completeness, immutable snapshots, exports and report scope."""
import unittest
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select
from app.models.employee import Employee, EmployeeRole, IikoEmployeeLink
from app.models.sales import SalesPeriodSnapshot, SalesSyncState, SalesTarget, SalesFact
from app.sales.reports import capture, finalize_reports, readiness
from app.sales.metrics import period
from app.schemas.sales import PeriodKind
from tests import test_sales_metrics as fixtures


class SalesReportsTests(unittest.IsolatedAsyncioTestCase):
    setUpBase = fixtures.SalesMetricsTests.setUp
    tearDown = fixtures.SalesMetricsTests.tearDown
    row = fixtures.SalesMetricsTests.row
    ingest = fixtures.SalesMetricsTests.ingest
    orders = fixtures.SalesMetricsTests.orders
    target = fixtures.SalesMetricsTests.target

    def setUp(self):
        self.setUpBase()
        SalesPeriodSnapshot.__table__.create(self.engine)
        with self.sessions.begin() as db:
            db.get(SalesSyncState, ('eclair', self.source_id)).history_from = date(2026, 8, 1)
            for link in db.scalars(select(IikoEmployeeLink)):
                link.valid_from = datetime(2026,8,1,tzinfo=timezone.utc)
        self.selected = period(PeriodKind.WEEK, anchor=date(2026, 9, 28), today=fixtures.NOW.date())

    def role(self, role, *, seller=False):
        with self.sessions.begin() as db:
            for employee in db.scalars(select(Employee)): employee.linked_user_id = None
        fixtures.SalesMetricsTests.role(self, role, seller=seller)

    def load_days(self, selected=None):
        selected = selected or self.selected
        day = selected.previous_start
        while day <= selected.end:
            self.ingest([], day=day)
            day += timedelta(days=1)
        self.ingest([self.row(**{'UniqOrderId.Id': str(uuid4()), 'OpenDate.Typed': str(selected.start), 'OpenTime': str(selected.start)+'T10:00:00', 'CloseTime': str(selected.start)+'T10:01:00', 'DishName': '=SUM(A1)', 'DishCategory': 'Десерты'})], day=selected.start)

    def capture(self, selected=None):
        with self.sessions.begin() as db:
            row, reason = capture(db, db.get(SalesSyncState, ('eclair', self.source_id)), selected or self.selected, now=fixtures.NOW)
            return (row.id if row else None), reason

    def test_incomplete_and_open_periods_are_not_final(self):
        report_id, reason = self.capture()
        self.assertIsNone(report_id); self.assertIn('не догружен', reason)
        current = period(PeriodKind.MONTH, today=fixtures.NOW.date())
        self.assertEqual(self.capture(current)[1], 'Период ещё не закрыт')
        response = self.client.get('/sales/analytics/reports?kind=week').json()
        self.assertFalse(response[0]['ready']); self.assertIn('не догружен', response[0]['reason'])
        self.load_days()
        self.assertIsNotNone(self.capture()[0])

    def test_intraday_checkpoint_is_not_a_complete_closed_day(self):
        from app.models.sales import SalesDaySync
        self.load_days()
        with self.sessions.begin() as db:
            day = db.get(SalesDaySync, ('eclair', self.source_id, self.selected.end))
            day.last_success_at = datetime(2026,10,4,12,tzinfo=timezone.utc)
        report_id, reason = self.capture()
        self.assertIsNone(report_id)
        self.assertIn('полных закрытых дней', reason)

    def test_snapshot_replay_live_correction_and_monthly_targets(self):
        self.role(EmployeeRole.DEPUTY_DIRECTOR)
        monthly = period(PeriodKind.MONTH, anchor=date(2026,9,1), today=fixtures.NOW.date())
        self.target('average_check', '700', month=date(2026,9,1))
        self.target('revenue', '50000', month=date(2026,9,1))
        self.load_days(monthly)
        report_id, reason = self.capture(monthly)
        self.assertIsNone(reason)
        before = self.client.get(f'/sales/analytics/reports/{report_id}').json()
        self.assertEqual(Decimal(before['data']['analytics']['metrics']['revenue']['fact']), 280)
        self.assertEqual(len(before['data']['sellers']), 1)
        self.assertEqual(Decimal(before['data']['analytics']['metrics']['average_check']['target']), 700)
        self.assertEqual(Decimal(before['data']['analytics']['metrics']['revenue']['target']), 50000)
        self.target('average_check', '900', month=date(2026,9,1), revision=1)
        self.ingest([], day=monthly.start)
        after = self.client.get(f'/sales/analytics/reports/{report_id}').json()
        self.assertEqual(before, after)
        self.assertEqual(self.capture(monthly)[0], report_id)
        live = self.client.get('/sales/analytics/overview?period=month&anchor=2026-09-01').json()
        self.assertEqual(Decimal(live['metrics']['revenue']['fact']), 0)
        self.assertEqual(Decimal(live['metrics']['average_check']['target']), 900)
        with self.assertRaises(RuntimeError):
            with self.sessions.begin() as db: db.get(SalesPeriodSnapshot, report_id).payload = {}
        with self.assertRaises(RuntimeError):
            with self.sessions.begin() as db: db.delete(db.get(SalesPeriodSnapshot, report_id))

    def test_all_role_report_export_matrix_and_tenant_boundary(self):
        self.load_days(); report_id, _ = self.capture()
        full = {EmployeeRole.ADMIN, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR, EmployeeRole.NETWORK_MANAGER}
        product = {EmployeeRole.CHEF_CONFECTIONER, EmployeeRole.HEAD_OF_PRODUCTION}
        for role in EmployeeRole:
            self.role(role, seller=role == EmployeeRole.SELLER)
            with self.subTest(role=role):
                for scope, allowed in [('full', role in full), ('products', role in full|product)]:
                    for endpoint in ['reports?kind=week&', f'reports/{report_id}?', f'reports/{report_id}/export?format=xlsx&']:
                        response = self.client.get('/sales/analytics/'+endpoint+'scope='+scope)
                        self.assertEqual(response.status_code, 200 if allowed else 403)
                    if allowed and scope == 'products':
                        data = self.client.get(f'/sales/analytics/reports/{report_id}?scope=products').json()['data']
                        self.assertEqual(set(data), {'products', 'product_changes', 'completeness', 'status'})
                for view in ['overview', 'points', 'sellers', 'products']:
                    response = self.client.get('/sales/analytics/export?format=xlsx&view='+view+'&period=week&anchor=2026-09-28')
                    self.assertEqual(response.status_code, 200 if role in full or (view == 'products' and role in product) else 403)
        self.role(EmployeeRole.ADMIN)
        from app.sales.reports import report_read
        from fastapi import HTTPException
        with self.sessions() as db:
            with self.assertRaises(HTTPException) as denied:
                report_read(db, 'another-company', report_id)
            self.assertEqual(denied.exception.status_code, 404)
        self.assertEqual(self.client.get(f'/sales/analytics/reports/{uuid4()}').status_code, 404)

    def test_exports_are_valid_and_filtered_and_no_iiko_in_request(self):
        self.load_days(); report_id, _ = self.capture()
        with patch('app.sales.sync.IikoServerClient', side_effect=AssertionError('Request cannot call iiko')):
            xlsx = self.client.get(f'/sales/analytics/reports/{report_id}/export?format=xlsx')
            pdf = self.client.get(f'/sales/analytics/reports/{report_id}/export?format=pdf')
        self.assertEqual(pdf.status_code, 200); self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertEqual(xlsx.status_code, 200)
        with ZipFile(BytesIO(xlsx.content)) as archive:
            for name in archive.namelist():
                if name.endswith('.xml') or name.endswith('.rels'): ET.fromstring(archive.read(name))
            for name in archive.namelist():
                if 'worksheets' in name:
                    self.assertNotIn(b'<f>', archive.read(name))
        response = self.client.get('/sales/analytics/export?view=products&category=unknown')
        with ZipFile(BytesIO(response.content)) as archive:
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
            self.assertEqual(len(sheet.findall('.//{*}row')), 1)
        self.assertEqual(self.client.get('/sales/analytics/export?view=products&employee_id='+str(self.employee_id)).status_code, 422)
        self.assertEqual(self.client.get('/sales/analytics/export?view=me').status_code, 422)
        self.assertEqual(self.client.get('/sales/analytics/reports?kind=custom').status_code, 422)

    def test_background_finalization_is_idempotent_and_recovers_after_backfill(self):
        context = SimpleNamespace(tenant_id='eclair', executed_at=fixtures.NOW)
        with self.sessions.begin() as db:
            first = finalize_reports(db, context, {})
        self.assertFalse(any(p['ready'] for p in first['periods']))
        self.load_days()
        with self.sessions.begin() as db: finalize_reports(db, context, {})
        with self.sessions() as db: ids = list(db.scalars(select(SalesPeriodSnapshot.id)))
        self.assertEqual(len(ids), 1)
        with self.sessions.begin() as db: finalize_reports(db, context, {})
        with self.sessions() as db: self.assertEqual(list(db.scalars(select(SalesPeriodSnapshot.id))), ids)


class SalesReportsAutomationTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the real scheduler/outbox SQLite fixture, not a mock scheduler.
    from tests.test_sales_schedule_ui import SalesScheduleUiTests as Fixture
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    row = fixtures.SalesMetricsTests.row
    ingest = fixtures.SalesMetricsTests.ingest
    orders = fixtures.SalesMetricsTests.orders
    client = Fixture.client

    async def test_reports_run_through_existing_scheduler_and_local_worker(self):
        from app.models.automation import AutomationSchedule, AutomationExecution, ExecutionStatus
        from app.automation.scheduler import run_scheduler_once
        from app.automation.local_actions import LocalAutomationActionExecutor
        from app.automation.outbox import SqlAlchemyOutboxStore, OutboxWorker, DeliveryStatus
        from unittest.mock import AsyncMock
        SalesTarget.__table__.create(self.engine)
        SalesPeriodSnapshot.__table__.create(self.engine)
        day = date(2026,9,21)
        while day <= date(2026,10,4):
            self.ingest([], day=day); day += timedelta(days=1)
        with self.sessions.begin() as db:
            db.get(SalesSyncState, ('eclair', self.source_id)).history_from = date(2026,9,21)
        with self.client() as client:
            response = client.post('/automation/schedules', json=dict(name='Отчёты', automation_type='sales.finalize_reports',
                scope_type='company', schedule_config={'type':'daily','time':'08:00'}, payload={}, recipients=[], timezone='Asia/Yekaterinburg', is_enabled=True))
            self.assertEqual(response.status_code,201)
            schedule_id = response.json()['id']
            self.assertEqual(client.post('/automation/schedules', json=dict(name='Bad', automation_type='sales.finalize_reports',
                scope_type='company', schedule_config={'type':'interval','minutes':15}, payload={}, recipients=[])).status_code,422)
        with self.sessions() as db:
            scheduled = db.get(AutomationSchedule,schedule_id).next_run_at.replace(tzinfo=timezone.utc)
        provider = AsyncMock()
        worker = OutboxWorker(store=SqlAlchemyOutboxStore(self.sessions), provider=provider, worker_id='reports-test',
            callback_url='http://unused.invalid', local_executor=LocalAutomationActionExecutor(self.sessions))
        with patch('app.sales.metrics.source_today', return_value=fixtures.NOW.date()):
            self.assertEqual(run_scheduler_once(self.sessions, now=scheduled).created,1)
            self.assertEqual((await worker.process_one()).status, DeliveryStatus.PUBLISHED)
            self.assertEqual(run_scheduler_once(self.sessions, now=scheduled+timedelta(days=1)).created,1)
            self.assertEqual((await worker.process_one()).status, DeliveryStatus.PUBLISHED)
        provider.send_command.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(len(list(db.scalars(select(SalesPeriodSnapshot)))),1)
            self.assertTrue(all(e.status == ExecutionStatus.SUCCEEDED for e in db.scalars(select(AutomationExecution))))
