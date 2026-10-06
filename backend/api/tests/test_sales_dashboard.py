"""A4 dashboard reads use existing role-scoped analytics contracts."""
import unittest
from tests import test_sales_metrics as fixtures
from sqlalchemy import select
from app.models.employee import Employee, EmployeeRole


class SalesDashboardTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.SalesMetricsTests.setUp
    tearDown = fixtures.SalesMetricsTests.tearDown
    row = fixtures.SalesMetricsTests.row
    ingest = fixtures.SalesMetricsTests.ingest
    orders = fixtures.SalesMetricsTests.orders
    def role(self, role, *, seller=False):
        with self.sessions.begin() as db:
            for employee in db.scalars(select(Employee)):
                employee.linked_user_id = None
        fixtures.SalesMetricsTests.role(self, role, seller=seller)

    def test_widget_endpoint_permissions_for_every_role(self):
        full = {EmployeeRole.ADMIN, EmployeeRole.NETWORK_MANAGER,
                EmployeeRole.DEPUTY_DIRECTOR, EmployeeRole.DIRECTOR}
        products = {EmployeeRole.CHEF_CONFECTIONER, EmployeeRole.HEAD_OF_PRODUCTION}
        for role in EmployeeRole:
            with self.subTest(role=role):
                self.role(role, seller=role == EmployeeRole.SELLER)
                for endpoint in ('overview', 'attention'):
                    response = self.client.get('/sales/analytics/' + endpoint + '?period=month')
                    self.assertEqual(response.status_code, 200 if role in full else 403)
                personal = self.client.get('/sales/analytics/me?period=month')
                self.assertEqual(personal.status_code, 200 if role == EmployeeRole.SELLER else 403)
                status = self.client.get('/sales/analytics/status')
                self.assertEqual(status.status_code, 200 if role in full | products | {EmployeeRole.SELLER} else 403)
                if role == EmployeeRole.SELLER:
                    self.assertIsNone(personal.json()['metrics']['revenue']['target'])
                    self.assertNotIn('sellers', personal.json())
                    self.assertNotIn('points', personal.json())

    def test_dashboard_current_month_coverage_and_target_write_boundary(self):
        result = self.client.get('/sales/analytics/overview?period=month')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['period']['start'], '2026-10-01')
        self.assertTrue(result.json()['completeness']['warning'])
        self.assertEqual(result.headers['Cache-Control'], 'no-store')
        for role in (EmployeeRole.DIRECTOR, EmployeeRole.NETWORK_MANAGER, EmployeeRole.SELLER):
            self.role(role, seller=role == EmployeeRole.SELLER)
            response = self.client.post('/sales/analytics/targets', json={
                'metric': 'average_check', 'month': '2026-10-01', 'value': '700'})
            self.assertEqual(response.status_code, 403)
        self.role(EmployeeRole.DEPUTY_DIRECTOR)
        self.assertEqual(self.client.post('/sales/analytics/targets', json={
            'metric': 'average_check', 'month': '2026-10-01', 'value': '700'}).status_code, 201)
