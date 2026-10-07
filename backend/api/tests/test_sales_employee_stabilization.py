"""Stable identity registration, seller-only mix and historical reuse boundaries."""
import unittest
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from app.models.employee import EmployeeRole, IikoEmployeeLink
from tests import test_sales_metrics as fixtures

NOW = fixtures.NOW


class SalesEmployeeStabilizationTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.SalesMetricsTests.setUp
    tearDown = fixtures.SalesMetricsTests.tearDown
    row = fixtures.SalesMetricsTests.row
    ingest = fixtures.SalesMetricsTests.ingest
    orders = fixtures.SalesMetricsTests.orders
    role = fixtures.SalesMetricsTests.role

    def test_first_confirmation_attributes_history_without_backdating(self):
        with self.sessions.begin() as db:
            link = db.scalar(select(IikoEmployeeLink))
            link.valid_from = NOW + timedelta(days=1)
        self.role(EmployeeRole.SELLER, seller=True)
        result = self.client.get('/sales/analytics/me').json()
        self.assertEqual(Decimal(result['metrics']['revenue']['fact']), 280)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(IikoEmployeeLink)).valid_from.date(), (NOW + timedelta(days=1)).date())

    def test_closed_reused_and_missing_identity_never_expand_history(self):
        with self.sessions.begin() as db:
            link = db.scalar(select(IikoEmployeeLink))
            link.valid_from = NOW
            link.valid_to = NOW + timedelta(days=1)
        self.assertIsNone(self.orders()[0].employee_id)
        with self.sessions.begin() as db:
            db.add(IikoEmployeeLink(tenant_id='eclair', employee_id=self.other_employee_id,
                iiko_user_id='cashier', iiko_display_name='Other owner',
                valid_from=NOW + timedelta(days=1), reason='Reused identity', created_by_user_id=1))
        self.assertIsNone(self.orders()[0].employee_id)
        self.ingest([self.row(**{'Cashier.Id': 'unconfirmed'})])
        self.assertIsNone(self.orders()[0].employee_id)

    def test_mix_merges_points_and_excludes_unattributed_orders(self):
        from app.models.employee import IikoDepartmentMapping
        from app.models.supply import Department, DepartmentBusinessType
        point, department, product = uuid4(), uuid4(), uuid4()
        with self.sessions.begin() as db:
            db.add(Department(id=department, tenant_id='eclair', code='second', name='Second',
                business_type=DepartmentBusinessType.RETAIL_POINT))
            db.flush()
            db.add(IikoDepartmentMapping(tenant_id='eclair', iiko_department_id=uuid4(),
                olap_department_id=point, eos_department_id=department, reason='Confirmed', decided_by_user_id=1))
        rows = [self.row(DishName='Cake', DishCategory='Dessert'),
            self.row(**{'Department.Id': str(point), 'UniqOrderId.Id': str(uuid4()), 'DishName': 'Cake'}),
            self.row(**{'UniqOrderId.Id': str(uuid4()), 'DishId': str(product), 'DishAmountInt': 1,
                'DishDiscountSumInt': 140, 'DishName': 'Tea'}),
            self.row(**{'UniqOrderId.Id': str(uuid4()), 'Cashier.Id': 'unknown', 'DishDiscountSumInt': 999})]
        from app.sales.service import ingest_day
        from app.models.sales import SalesSyncState
        from tests.test_sales_metrics import DAY
        with self.sessions.begin() as db:
            ingest_day(db, rows, state=db.get(SalesSyncState, ('eclair', self.source_id)),
                day=DAY, department_ids=[self.point, point], seen_at=NOW)
        previous_day = DAY.replace(month=9, day=15)
        self.ingest([self.row(**{'OpenDate.Typed': str(previous_day), 'OpenTime': str(previous_day) + 'T10:00:00',
            'CloseTime': str(previous_day) + 'T10:01:00', 'UniqOrderId.Id': str(uuid4()),
            'DishAmountInt': 1, 'DishDiscountSumInt': 70})], day=previous_day)
        query = '?view=seller-products&employee_id=' + str(self.employee_id)
        result = self.client.get('/sales/analytics/workspace' + query)
        self.assertEqual(result.status_code, 200, result.text)
        mix = result.json()['seller_mix']
        self.assertEqual(Decimal(mix['revenue']), 700)
        self.assertEqual(sum(Decimal(p['revenue']) for p in mix['products']), 700)
        cake = next(p for p in mix['products'] if p['iiko_product_id'] == str(self.product))
        self.assertEqual(Decimal(cake['quantity']), 4)
        self.assertEqual(Decimal(cake['share_percent']), 80)
        self.assertEqual(Decimal(cake['previous_quantity']), 1)
        self.assertEqual(Decimal(cake['previous_revenue']), 70)
        self.assertEqual(Decimal(cake['revenue_change']), 490)
        self.assertEqual(Decimal(cake['quantity_change']), 3)
        filtered = self.client.get('/sales/analytics/workspace' + query + '&iiko_product_id=' + str(self.product)).json()['seller_mix']
        self.assertEqual(Decimal(filtered['products'][0]['share_percent']), 80)
        self.role(EmployeeRole.SELLER, seller=True)
        own = self.client.get('/sales/analytics/workspace?view=me-products').json()['seller_mix']
        self.assertEqual(own, mix)

    def test_mix_role_matrix_and_seller_cannot_choose_identity(self):
        full = {EmployeeRole.ADMIN, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR, EmployeeRole.NETWORK_MANAGER}
        for role in EmployeeRole:
            self.role(role, seller=role == EmployeeRole.SELLER)
            with self.subTest(role=role):
                self.assertEqual(self.client.get('/sales/analytics/workspace?view=seller-products&employee_id=' + str(self.employee_id)).status_code, 200 if role in full else 403)
                self.assertEqual(self.client.get('/sales/analytics/workspace?view=me-products').status_code, 200 if role == EmployeeRole.SELLER else 403)
        self.role(EmployeeRole.SELLER, seller=True)
        for key in ['employee_id', 'department_id']:
            self.assertEqual(self.client.get('/sales/analytics/workspace?view=me-products&' + key + '=' + str(uuid4())).status_code, 422)
