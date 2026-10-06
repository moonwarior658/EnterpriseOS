"""Completeness, bundled reads, and sync transaction/lease boundaries."""
import asyncio
import unittest
from datetime import date, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import event, select
from tests import test_sales_metrics as fixtures
DAY, NOW = fixtures.DAY, fixtures.NOW
from app.integrations.iiko.config import IikoSettings
from app.models.employee import EmployeeRole
from app.models.sales import SalesSyncState, SalesDaySync
from app.sales import metrics, sync
from app.sales.service import SalesContractError


class SalesStabilizationTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.SalesMetricsTests.setUp
    tearDown = fixtures.SalesMetricsTests.tearDown
    row = fixtures.SalesMetricsTests.row
    ingest = fixtures.SalesMetricsTests.ingest
    orders = fixtures.SalesMetricsTests.orders
    role = fixtures.SalesMetricsTests.role

    def test_completeness_empty_days_and_future_are_not_missing_sales(self):
        self.ingest([], day=DAY - timedelta(days=1))
        result = self.client.get('/sales/analytics/workspace').json()
        coverage = result['completeness']
        self.assertTrue(coverage['warning'])
        self.assertEqual(coverage['current']['loaded_days'], 2)
        self.assertEqual(coverage['current']['expected_days'], NOW.day)
        days = {r['date']: r['metrics']['revenue']['fact'] for r in result['analytics']['dynamics']}
        self.assertEqual(days[str(DAY - timedelta(days=1))], '0')
        self.assertIsNone(days['2026-10-01'])
        self.assertIsNone(days['2026-10-31'])
        self.assertEqual(self.client.get('/sales/analytics/points').headers['X-Sales-Data-Complete'], 'false')

    def test_workspace_one_reconciliation_no_iiko_and_connection_released_before_calculation(self):
        active = [0]
        event.listen(self.engine, 'checkout', lambda *args: active.__setitem__(0, active[0] + 1))
        event.listen(self.engine, 'checkin', lambda *args: active.__setitem__(0, active[0] - 1))
        original = metrics.reconcile_loaded
        def calculate(*args, **kwargs):
            self.assertEqual(active[0], 0)
            return original(*args, **kwargs)
        with patch('app.sales.sync.IikoServerClient', side_effect=AssertionError('request must not sync')):
            with patch('app.sales.metrics.reconcile_loaded', side_effect=calculate) as reconciliation:
                self.assertEqual(self.client.get('/sales/analytics/workspace').status_code, 200)
                self.assertEqual(reconciliation.call_count, 1)
            for endpoint in ['status', 'overview', 'points', 'sellers', 'attention', 'products', 'targets']:
                self.assertEqual(self.client.get('/sales/analytics/' + endpoint).status_code, 200)

    def test_workspace_role_and_filter_boundaries(self):
        full = {EmployeeRole.ADMIN, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR, EmployeeRole.NETWORK_MANAGER}
        product = full | {EmployeeRole.CHEF_CONFECTIONER, EmployeeRole.HEAD_OF_PRODUCTION}
        for role in EmployeeRole:
            with self.sessions.begin() as db:
                from app.models.employee import Employee
                for employee in db.scalars(select(Employee)):
                    employee.linked_user_id = None
            self.role(role, seller=role == EmployeeRole.SELLER)
            for view in ['overview', 'points', 'sellers', 'products', 'me']:
                allowed = role == EmployeeRole.SELLER if view == 'me' else role in product if view == 'products' else role in full
                with self.subTest(role=role, view=view):
                    self.assertEqual(self.client.get('/sales/analytics/workspace?view=' + view).status_code, 200 if allowed else 403)
        with self.sessions.begin() as db:
            from app.models.employee import Employee
            for employee in db.scalars(select(Employee)):
                employee.linked_user_id = None
        self.role(EmployeeRole.SELLER, seller=True)
        self.assertEqual(self.client.get('/sales/analytics/workspace?view=me&employee_id=' + str(uuid4())).status_code, 422)
        with self.sessions.begin() as db:
            db.get(Employee, self.employee_id).linked_user_id = None
        self.role(EmployeeRole.CHEF_CONFECTIONER)
        self.assertEqual(self.client.get('/sales/analytics/workspace?view=products&staff=all').status_code, 422)

    def sync_fixture(self):
        settings = IikoSettings(enabled=True, base_url='https://example.invalid/resto/', login='test', password='test')
        sid = sync.source_identity(settings)
        with self.sessions.begin() as db:
            # Existing fixture already has a fact and its checkpoint; changing the source
            # for this test requires preserving their foreign-key relationship.
            db.add(SalesSyncState(tenant_id='eclair', source_id=sid, source_timezone='Asia/Yekaterinburg',
                history_from=date(2026, 4, 6), backfill_next=date(2026, 6, 15)))
        return settings, sid

    async def test_sync_commits_each_day_and_releases_connection_during_io(self):
        settings, sid = self.sync_fixture()
        active = [0]
        event.listen(self.engine, 'checkout', lambda *args: active.__setitem__(0, active[0] + 1))
        event.listen(self.engine, 'checkin', lambda *args: active.__setitem__(0, active[0] - 1))
        client = AsyncMock(); client.__aenter__.return_value = client
        calls = [0]
        async def get_rows(body):
            self.assertEqual(active[0], 0)
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError('private provider details')
            return []
        client.get_sales_olap.side_effect = get_rows
        with patch('app.sales.sync.get_iiko_settings', return_value=settings), patch('app.sales.sync.IikoServerClient', return_value=client):
            with self.assertRaisesRegex(SalesContractError, '^SALES_SYNC_FAILED$'):
                await sync.sync_sales(self.sessions, tenant_id='eclair', source_id=sid, now=NOW)
        with self.sessions() as db:
            days = list(db.scalars(select(SalesDaySync.business_date).where(SalesDaySync.source_id == sid)))
            self.assertEqual(days, [NOW.astimezone(timezone(timedelta(hours=5))).date()])
            state = db.get(SalesSyncState, ('eclair', sid))
            self.assertIsNone(state.lease_token)
            self.assertIsNone(state.last_success_at)

    async def test_concurrent_sync_skips_and_expired_worker_cannot_release_new_lease(self):
        settings, sid = self.sync_fixture()
        client = AsyncMock(); client.__aenter__.return_value = client
        replacement = uuid4()
        async def get_rows(body):
            result = await sync.sync_sales(self.sessions, tenant_id='eclair', source_id=sid, now=NOW)
            self.assertTrue(result['skipped'])
            with self.sessions.begin() as db:
                state = db.get(SalesSyncState, ('eclair', sid))
                state.lease_token = replacement
                state.lease_until = sync.wall_now() + timedelta(minutes=5)
            return []
        client.get_sales_olap.side_effect = get_rows
        with patch('app.sales.sync.get_iiko_settings', return_value=settings), patch('app.sales.sync.IikoServerClient', return_value=client):
            with self.assertRaisesRegex(SalesContractError, '^SALES_SYNC_LEASE_LOST$'):
                await sync.sync_sales(self.sessions, tenant_id='eclair', source_id=sid, now=NOW)
        with self.sessions() as db:
            self.assertEqual(db.get(SalesSyncState, ('eclair', sid)).lease_token, replacement)
            self.assertEqual(list(db.scalars(select(SalesDaySync).where(SalesDaySync.source_id == sid))), [])

    def test_missing_history_prioritizes_latest_month_and_retains_correction_cursor(self):
        with self.sessions() as db:
            state = db.get(SalesSyncState, ('eclair', self.source_id))
            state.history_from = date(2026, 4, 6); state.backfill_next = date(2026, 6, 15)
            days, cursor = sync.sync_days(db, state, date(2026, 10, 6))
        self.assertIn(date(2026, 9, 1), days)
        self.assertIn(date(2026, 9, 28), days)
        self.assertEqual(cursor, date(2026, 6, 22))
        self.assertLessEqual(len(days), 45)
        self.assertLess(sync.required_history_start(date(2026, 10, 6)), date(2026, 4, 6))

    async def test_read_admission_queues_before_next_dependency(self):
        from app.api.routes.sales import analytics_read_slot
        request = type('Request', (), {'method': 'GET'})()
        entered = [0]; maximum = [0]
        async def read():
            async for _ in analytics_read_slot(request):
                entered[0] += 1; maximum[0] = max(maximum[0], entered[0])
                await asyncio.sleep(.01)
                entered[0] -= 1
        await asyncio.gather(*(read() for _ in range(20)))
        self.assertEqual(maximum[0], 4)
