"""A2 formulas, public contracts, authorization and historical scope."""
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from tests import test_sales_foundation as foundation
DAY, NOW = foundation.DAY, foundation.NOW
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.api.dependencies import get_current_user
from app.api.routes.sales import router
from app.db.session import get_db
from app.models.audit import AuditEvent
from app.models.employee import Employee, EmployeeRole, EmployeeRoleAssignment, IikoEmployeeLink, IikoDepartmentMapping
from app.models.sales import SalesTarget
from app.models.supply import Department, DepartmentBusinessType
from app.models.user import User, UserAccountType
from app.sales.metrics import attention, create_target, latest_targets, metric, period, source_state
from app.schemas.sales import PeriodKind, TargetCreate, TargetMetric


class SalesMetricsTests(unittest.IsolatedAsyncioTestCase):
    row = foundation.SalesFoundationTests.row
    ingest = foundation.SalesFoundationTests.ingest
    orders = foundation.SalesFoundationTests.orders

    def setUp(self):
        foundation.SalesFoundationTests.setUp(self)
        SalesTarget.__table__.create(self.engine)
        self.ingest([self.row()])
        self.app = FastAPI()
        self.app.include_router(router)
        def db_dependency():
            with self.sessions() as db:
                yield db
        def actor():
            with self.sessions() as db:
                return db.get(User, 1)
        self.app.dependency_overrides[get_db] = db_dependency
        self.app.dependency_overrides[get_current_user] = actor
        self.client = TestClient(self.app)
        self.clock = patch('app.sales.metrics.source_today', return_value=NOW.date())
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.client.close()
        self.engine.dispose()

    def role(self, role, *, seller=False):
        with self.sessions.begin() as db:
            db.get(Employee, self.admin_employee_id).linked_user_id = None
            db.flush()
            eid = self.employee_id if seller else self.admin_employee_id
            db.get(Employee, eid).linked_user_id = 1
            for r in db.scalars(select(EmployeeRoleAssignment)).all():
                db.delete(r)
            db.flush()
            db.add(EmployeeRoleAssignment(tenant_id='eclair', employee_id=eid, role=role,
                valid_from=self.started, reason='test', assigned_by_user_id=1))

    def target(self, metric_name, value, *, month=date(2026,10,1), revision=0):
        with self.sessions.begin() as db:
            return create_target(db, db.get(User,1), TargetCreate(metric=metric_name, month=month,
                value=Decimal(value), expected_revision=revision))

    def test_decimal_formulas_free_returns_and_deleted(self):
        self.ingest([self.row(DishAmountInt=Decimal('2.5'), DishDiscountSumInt=Decimal('299.99')),
            self.row(DishAmountInt=10,DishDiscountSumInt=0),
            self.row(DishAmountInt=-1,DishDiscountSumInt=-100,DishReturnSum=100,Storned='TRUE'),
            self.row(DishAmountInt=100,DishDiscountSumInt=999,OrderDeleted='DELETED')])
        data=self.client.get('/sales/analytics/overview').json()['metrics']
        self.assertEqual(Decimal(data['revenue']['fact']), Decimal('199.99'))
        self.assertEqual(Decimal(data['check_count']['fact']), 1)
        self.assertEqual(Decimal(data['average_check']['fact']), Decimal('199.99'))
        self.assertEqual(Decimal(data['fullness']['fact']), Decimal('1.5'))
        self.ingest([self.row(),self.row(DishAmountInt=-2,DishDiscountSumInt=-280,Storned='TRUE')])
        data=self.client.get('/sales/analytics/overview').json()['metrics']
        self.assertEqual(Decimal(data['check_count']['fact']),0)
        self.assertIsNone(data['average_check']['fact'])
        self.assertEqual(data['fullness']['status'],'no_data')
        self.assertEqual(self.client.get('/sales/analytics/products').json()['products'],[])

    def test_status_boundaries_and_comparison_zero(self):
        for fact,status in [('84.999','red'),('85','warning'),('99.99','warning'),('100','green'),('120','green')]:
            result=metric(Decimal(fact),Decimal(50),Decimal(100))
            self.assertEqual(result.status,status)
            self.assertEqual(result.completion_percent,Decimal(fact))
        self.assertIsNone(metric(Decimal(10),Decimal(0)).change_percent)
        self.assertEqual(metric(None,target=Decimal(100)).status,'no_data')
        self.assertEqual(metric(Decimal(0)).status,'no_target')

    def test_periods_equal_duration_month_leap_week_custom_and_limits(self):
        p=period(PeriodKind.MONTH,anchor=date(2024,3,15),today=date(2024,3,15))
        self.assertEqual((p.start,p.end,p.previous_start,p.previous_end),
            (date(2024,3,1),date(2024,3,31),date(2024,1,30),date(2024,2,29)))
        p=period(PeriodKind.WEEK,anchor=date(2026,1,1),today=date(2026,1,1))
        self.assertEqual((p.start,p.end,p.previous_start,p.previous_end),
            (date(2025,12,29),date(2026,1,4),date(2025,12,22),date(2025,12,28)))
        p=period(PeriodKind.CUSTOM,start=date(2026,10,1),end=date(2026,10,10),today=date(2026,10,10))
        self.assertEqual((p.previous_start,p.previous_end),(date(2026,9,21),date(2026,9,30)))
        for kwargs in [dict(start=date(2026,10,6),end=date(2026,10,5)),
                       dict(start=date(2026,3,1),end=DAY),dict(start=DAY,end=date(2026,10,7))]:
            with self.assertRaises(HTTPException): period(PeriodKind.CUSTOM,today=NOW.date(),**kwargs)
        for query in ['period=custom','period=week&start=2026-10-01','period=bad','anchor=2026-10-07']:
            self.assertEqual(self.client.get('/sales/analytics/overview?'+query).status_code,422)

    def test_complete_role_matrix_and_no_legacy_admin_bypass(self):
        full={EmployeeRole.ADMIN,EmployeeRole.DIRECTOR,EmployeeRole.DEPUTY_DIRECTOR,EmployeeRole.NETWORK_MANAGER}
        product=full|{EmployeeRole.CHEF_CONFECTIONER,EmployeeRole.HEAD_OF_PRODUCTION}
        for role in EmployeeRole:
            self.role(role,seller=role==EmployeeRole.SELLER)
            with self.subTest(role=role):
                for path in ['overview','points','sellers','attention']:
                    self.assertEqual(self.client.get('/sales/analytics/'+path).status_code,200 if role in full else 403)
                self.assertEqual(self.client.get('/sales/analytics/products').status_code,200 if role in product else 403)
                self.assertEqual(self.client.get('/sales/analytics/me').status_code,200 if role==EmployeeRole.SELLER else 403)
                self.assertEqual(self.client.get('/sales/analytics/targets').status_code,200 if role in full|{EmployeeRole.SELLER} else 403)
                result=self.client.post('/sales/analytics/targets',json={'metric':'fullness','month':'2026-10-01','value':'3'})
                self.assertEqual(result.status_code,201 if role==EmployeeRole.DEPUTY_DIRECTOR else 403)
        with self.sessions.begin() as db:
            for r in db.scalars(select(EmployeeRoleAssignment)).all(): db.delete(r)
        self.assertEqual(self.client.get('/sales/analytics/overview').status_code,403)

    def test_inactive_service_dismissed_and_expired_roles_fail_closed(self):
        with self.sessions.begin() as db: db.get(User,1).is_active=False
        self.assertEqual(self.client.get('/sales/analytics/overview').status_code,403)
        with self.sessions.begin() as db:
            user=db.get(User,1);user.is_active=True;user.account_type=UserAccountType.SERVICE
        self.assertEqual(self.client.get('/sales/analytics/overview').status_code,403)
        with self.sessions.begin() as db:
            db.get(User,1).account_type=UserAccountType.HUMAN
            e=db.get(Employee,self.admin_employee_id)
            e.status='DISMISSED';e.dismissal_date=NOW.date();e.dismissal_reason='test'
        self.assertEqual(self.client.get('/sales/analytics/overview').status_code,403)
        with self.sessions.begin() as db:
            e=db.get(Employee,self.admin_employee_id)
            e.status='ACTIVE';e.dismissal_date=None;e.dismissal_reason=None
            for r in db.scalars(select(EmployeeRoleAssignment)): r.valid_to=NOW-timedelta(days=1)
        self.assertEqual(self.client.get('/sales/analytics/overview').status_code,403)

    def test_seller_strict_queries_own_links_multiple_points_and_unknown(self):
        self.role(EmployeeRole.SELLER,seller=True)
        self.assertEqual(Decimal(self.client.get('/sales/analytics/me').json()['metrics']['revenue']['fact']),280)
        for query in ['employee_id='+str(self.other_employee_id),'department_id='+str(self.department_id),
                      'staff=all','source_id=other','tenant_id=other']:
            self.assertEqual(self.client.get('/sales/analytics/me?'+query).status_code,422)
        second_point, second_department=uuid4(),uuid4()
        with self.sessions.begin() as db:
            db.add(Department(id=second_department,tenant_id='eclair',code='B',name='B',business_type=DepartmentBusinessType.RETAIL_POINT))
            db.flush()
            db.add(IikoDepartmentMapping(tenant_id='eclair',iiko_department_id=uuid4(),olap_department_id=second_point,
                eos_department_id=second_department,reason='test',decided_by_user_id=1))
        with self.sessions.begin() as db:
            from app.sales.service import ingest_day
            state=source_state(db,'eclair')
            ingest_day(db,[self.row(),self.row(**{'Department.Id':str(second_point),'UniqOrderId.Id':str(uuid4())}),
                self.row(**{'UniqOrderId.Id':str(uuid4()),'Cashier.Id':'unknown'})],
                state=state,day=DAY,department_ids=[self.point,second_point],seen_at=NOW)
        data=self.client.get('/sales/analytics/me').json()
        self.assertEqual(Decimal(data['metrics']['revenue']['fact']),560)
        self.assertNotIn('department_id',str(data));self.assertNotIn('employee_name',str(data))
        self.assertEqual(Decimal(data['metrics']['check_count']['fact']),2)
        # Ending historical identity after the sale preserves ownership.
        with self.sessions.begin() as db:
            db.scalar(select(IikoEmployeeLink)).valid_to=NOW
        self.assertEqual(Decimal(self.client.get('/sales/analytics/me').json()['metrics']['revenue']['fact']),560)
        with self.sessions.begin() as db:
            db.scalar(select(IikoEmployeeLink)).valid_to=self.started+timedelta(days=1)
        self.assertEqual(Decimal(self.client.get('/sales/analytics/me').json()['metrics']['revenue']['fact']),0)

    def test_target_revisions_audit_optimistic_conflict_and_tenant_scope(self):
        self.role(EmployeeRole.DEPUTY_DIRECTOR)
        first=self.target(TargetMetric.AVERAGE_CHECK,'700')
        second=self.target(TargetMetric.AVERAGE_CHECK,'730',revision=1)
        self.assertEqual((first.revision,second.revision),(1,2))
        with self.sessions() as db:
            rows=list(db.scalars(select(AuditEvent).where(AuditEvent.entity_type=='SalesTarget')))
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[1].authorized_as,'DEPUTY_DIRECTOR')
            self.assertEqual(rows[1].before['revision'],1)
            self.assertEqual(latest_targets(db,'eclair')[(date(2026,10,1),'average_check')],730)
            self.assertEqual(latest_targets(db,'other'),{})
        body={'metric':'average_check','month':'2026-10-01','value':'750','expected_revision':1}
        self.assertEqual(self.client.post('/sales/analytics/targets',json=body).status_code,409)
        self.assertEqual(len(self.client.get('/sales/analytics/targets').json()),2)
        with patch('app.sales.metrics.record_audit_event',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):
                with self.sessions.begin() as db:
                    create_target(db,db.get(User,1),TargetCreate(metric='fullness',month=date(2026,10,1),value=3))
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(SalesTarget)).all()),2)
        for changed in [{'value':'0'},{'value':'-1'},{'value':'NaN'},{'month':'2026-10-02'}, {'value':'1000000000000000000'}]:
            self.assertEqual(self.client.post('/sales/analytics/targets',json=dict(body,**changed)).status_code,422)

    def test_kpi_network_month_plan_and_personal_revenue_no_target(self):
        self.role(EmployeeRole.DEPUTY_DIRECTOR)
        self.target('average_check','350');self.target('fullness','2');self.target('revenue','1000')
        data=self.client.get('/sales/analytics/overview').json()['metrics']
        self.assertEqual(Decimal(data['average_check']['completion_percent']),80)
        self.assertEqual(data['average_check']['status'],'red')
        self.assertEqual(data['fullness']['status'],'green')
        self.assertEqual(Decimal(data['revenue']['completion_percent']),28)
        self.assertIsNone(data['check_count']['target'])
        self.assertIsNone(self.client.get('/sales/analytics/overview?period=week').json()['metrics']['revenue']['target'])
        self.assertIsNone(self.client.get('/sales/analytics/overview?employee_id='+str(self.employee_id)).json()['metrics']['revenue']['target'])
        self.role(EmployeeRole.SELLER,seller=True)
        self.assertIsNone(self.client.get('/sales/analytics/me').json()['metrics']['revenue']['target'])
        self.assertEqual({t['metric'] for t in self.client.get('/sales/analytics/targets').json()},{'average_check','fullness'})
        self.assertEqual(self.client.get('/sales/analytics/targets?metric=revenue').status_code,403)

    def test_mixed_month_targets_segments_and_previous_facts(self):
        self.role(EmployeeRole.DEPUTY_DIRECTOR)
        self.target('average_check','700',month=date(2026,9,1));self.target('average_check','350')
        day=date(2026,9,30)
        self.ingest([self.row(**{'OpenDate.Typed':str(day),'OpenTime':str(day)+'T10:00:00',
            'UniqOrderId.Id':str(uuid4()),'DishDiscountSumInt':700})],day)
        data=self.client.get('/sales/analytics/overview?period=custom&start=2026-09-30&end=2026-10-05').json()
        self.assertEqual(len(data['target_segments']),2)
        self.assertEqual(data['metrics']['average_check']['status'],'mixed_targets')
        self.assertIsNone(data['metrics']['average_check']['target'])
        data=self.client.get('/sales/analytics/overview').json()['metrics']
        self.assertEqual(Decimal(data['revenue']['previous']),700)
        self.assertEqual(Decimal(data['revenue']['change']),-420)
        self.assertEqual(Decimal(data['revenue']['change_percent']),-60)

    def test_attention_worst_single_kpi_top_two_and_dismissal_filter(self):
        self.role(EmployeeRole.DEPUTY_DIRECTOR)
        self.target('average_check','350');self.target('fullness','3')
        rows=self.client.get('/sales/analytics/attention').json()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['employee_id'],str(self.employee_id))
        with self.sessions.begin() as db:
            e=db.get(Employee,self.employee_id);e.status='DISMISSED';e.dismissal_date=NOW.date();e.dismissal_reason='test'
        self.assertEqual(self.client.get('/sales/analytics/sellers').json(),[])
        self.assertEqual(self.client.get('/sales/analytics/attention').json(),[])
        self.assertEqual(len(self.client.get('/sales/analytics/sellers?staff=dismissed').json()),1)
        self.assertEqual(len(self.client.get('/sales/analytics/sellers?staff=all').json()),1)
        self.assertEqual(self.client.get('/sales/analytics/sellers?staff=unknown').status_code,422)
        # Worse single KPI wins even if the other KPI is better, without a score.
        rows=[dict(employee_id=str(i),metrics={'average_check':{'completion_percent':Decimal(a)},
            'fullness':{'completion_percent':Decimal(b)}}) for i,a,b in [(1,84,110),(2,95,60),(3,70,99),(4,85,85)]]
        self.assertEqual([r['employee_id'] for r in attention(rows)],['2','3'])

    def test_cross_day_refund_restates_previous_period_and_product_scope(self):
        self.ingest([self.row(**{'UniqOrderId.Id':str(uuid4()),'SourceOrderId':str(self.order),
            'OpenDate.Typed':'2026-10-06','OpenTime':'2026-10-06T12:00:00',
            'DishAmountInt':-1,'DishDiscountSumInt':0,'DishReturnSum':140,'Storned':'TRUE',
            'Cashier.Id':'unknown','DeletedWithWriteoff':'DELETED_WITH_WRITEOFF'})],NOW.date())
        result=self.client.get('/sales/analytics/overview?period=custom&start=2026-10-06&end=2026-10-06').json()['metrics']
        self.assertEqual(Decimal(result['revenue']['fact']),0)
        self.assertEqual(Decimal(result['revenue']['previous']),140)
        self.role(EmployeeRole.CHEF_CONFECTIONER)
        data=self.client.get('/sales/analytics/products').json()['products']
        self.assertEqual(Decimal(data[0]['quantity']),1)
        self.assertEqual(Decimal(data[0]['revenue']),140)
        self.assertNotIn('employee',str(data));self.assertNotIn('target',str(data))
        self.assertEqual(self.client.get('/sales/analytics/products?employee_id='+str(self.employee_id)).status_code,422)

    def test_append_only_model_and_target_date_semantics(self):
        self.role(EmployeeRole.DEPUTY_DIRECTOR)
        target=self.target('fullness','3')
        for mutation in ('update','delete'):
            with self.assertRaisesRegex(RuntimeError,'immutable'):
                with self.sessions.begin() as db:
                    stored=db.get(SalesTarget,target.id)
                    if mutation=='update': stored.value=Decimal(4)
                    else: db.delete(stored)
                    db.flush()
        self.target('fullness','5',month=date(2026,11,1))
        # Future targets never apply retroactively to October.
        result=self.client.get('/sales/analytics/overview').json()['metrics']['fullness']
        self.assertEqual(Decimal(result['target']),3)

    def test_historical_link_reuse_and_other_tenant_never_leak(self):
        self.role(EmployeeRole.SELLER,seller=True)
        with self.sessions.begin() as db:
            db.scalar(select(IikoEmployeeLink)).valid_to=NOW
            db.flush()
            db.add(IikoEmployeeLink(tenant_id='eclair',employee_id=self.other_employee_id,
                iiko_user_id='cashier',iiko_display_name='new owner',valid_from=NOW,
                reason='test',created_by_user_id=1))
        result=self.client.get('/sales/analytics/me').json()['metrics']
        self.assertEqual(Decimal(result['revenue']['fact']),280)
        with self.sessions.begin() as db:
            db.get(User,1).tenant_id='other'
        self.assertEqual(self.client.get('/sales/analytics/me').status_code,403)

    def test_mixed_target_attention_uses_explicit_month_segments(self):
        self.role(EmployeeRole.DEPUTY_DIRECTOR)
        self.target('average_check','100',month=date(2026,9,1))
        self.target('average_check','700')
        day=date(2026,9,30)
        self.ingest([self.row(**{'OpenDate.Typed':str(day),'OpenTime':str(day)+'T10:00:00',
            'UniqOrderId.Id':str(uuid4()),'DishDiscountSumInt':100})],day)
        rows=self.client.get('/sales/analytics/attention?period=custom&start=2026-09-30&end=2026-10-05').json()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['metrics']['average_check']['status'],'mixed_targets')
        self.assertEqual(Decimal(rows[0]['target_segments'][1]['metrics']['average_check']['completion_percent']),40)

    def test_rbac_uses_existing_catalog_without_spec_aliases(self):
        from app.sales.metrics import FULL_ROLES, PRODUCT_ROLES
        self.assertEqual(set(FULL_ROLES), {EmployeeRole.ADMIN, EmployeeRole.DIRECTOR,
            EmployeeRole.DEPUTY_DIRECTOR, EmployeeRole.NETWORK_MANAGER})
        self.assertEqual(set(PRODUCT_ROLES) - set(FULL_ROLES),
            {EmployeeRole.CHEF_CONFECTIONER, EmployeeRole.HEAD_OF_PRODUCTION})
        for absent in ('EKLER_MANAGER', 'CHEF', 'PRODUCTION_MANAGER'):
            with self.assertRaises(ValueError): EmployeeRole(absent)

    def test_previous_period_always_adjacent_and_equal_length(self):
        for anchor in (date(2026,10,6), date(2026,3,10), date(2024,2,15), date(2026,1,1)):
            for kind in (PeriodKind.MONTH, PeriodKind.WEEK):
                selected=period(kind,anchor=anchor,today=anchor)
                self.assertEqual(selected.start-selected.previous_end,timedelta(days=1))
                self.assertEqual(selected.end-selected.start,selected.previous_end-selected.previous_start)
        result=self.client.get('/sales/analytics/overview').json()['period']
        self.assertEqual((result['previous_start'],result['previous_end']),('2026-08-31','2026-09-30'))

    def test_bounded_path_excludes_unrelated_history_but_includes_late_refunds(self):
        from app.sales.service import reconcile, reconciliation_facts
        old_day=date(2020,1,1)
        self.ingest([self.row(**{'UniqOrderId.Id':str(uuid4()),'OpenDate.Typed':str(old_day),
            'OpenTime':str(old_day)+'T10:00:00'}) for _ in range(40)],old_day)
        refund_day=date(2027,2,1)
        self.ingest([self.row(**{'UniqOrderId.Id':str(uuid4()),'SourceOrderId':str(self.order),
            'OpenDate.Typed':str(refund_day),'OpenTime':str(refund_day)+'T10:00:00',
            'DishAmountInt':-1,'DishDiscountSumInt':0,'DishReturnSum':140,'Storned':'TRUE'})],refund_day)
        with self.sessions() as db:
            state=source_state(db,'eclair')
            loaded=reconciliation_facts(db,state,start=DAY,end=DAY)
            self.assertEqual(len(loaded),2)
            self.assertNotIn(old_day,{f.business_date for f in loaded})
            self.assertIn(refund_day,{f.business_date for f in loaded})
            bounded=reconcile(db,state,start=DAY,end=DAY)
            full=[o for o in reconcile(db,state) if o.business_date==DAY]
            self.assertEqual(bounded,full)
            self.assertEqual(bounded[0].revenue,140)
        from app.sales import service as sales_service
        calls=[]
        original=sales_service.reconciliation_facts
        def capture(db,state,**kwargs):
            self.assertEqual(kwargs,dict(start=date(2026,8,31),end=date(2026,10,31)))
            result=original(db,state,**kwargs)
            calls.append(len(result))
            return result
        with patch('app.sales.service.reconciliation_facts',side_effect=capture):
            for endpoint in ('overview','points','sellers','attention','products'):
                self.assertEqual(self.client.get('/sales/analytics/'+endpoint).status_code,200)
            self.role(EmployeeRole.SELLER,seller=True)
            result=self.client.get('/sales/analytics/me')
            self.assertEqual(result.status_code,200)
            self.assertEqual(Decimal(result.json()['metrics']['revenue']['fact']),140)
        self.assertEqual(calls,[2]*6)

    def test_bounded_reconciliation_preserves_fail_closed_return_graphs(self):
        from app.sales.service import reconcile
        first,second=uuid4(),uuid4()
        day=date(2027,2,1)
        def refund(order_id,source_id):
            return self.row(**{'UniqOrderId.Id':str(order_id),'SourceOrderId':str(source_id),
                'OpenDate.Typed':str(day),'OpenTime':str(day)+'T10:00:00',
                'DishAmountInt':-1,'DishDiscountSumInt':-140,'Storned':'TRUE'})
        cases=[
            [refund(first,self.order),refund(second,first)],
            [refund(first,self.order),refund(self.order,first)],
            [refund(first,self.order),refund(first,second)],
        ]
        for rows in cases:
            self.ingest([self.row()])
            self.ingest(rows,day)
            with self.sessions() as db:
                state=source_state(db,'eclair')
                actual=reconcile(db,state,start=DAY,end=DAY)
                expected=[o for o in reconcile(db,state) if o.business_date==DAY]
                self.assertEqual(actual,expected)
                self.assertTrue(all(o.excluded for o in actual))

    def test_bounded_reconciliation_validates_period_and_batches_receipts(self):
        from app.sales.service import reconciliation_facts, SalesContractError
        self.ingest([self.row(**{'UniqOrderId.Id':str(uuid4())}) for _ in range(405)])
        with self.sessions() as db:
            state=source_state(db,'eclair')
            self.assertEqual(len(reconciliation_facts(db,state,start=DAY,end=DAY)),405)
            self.assertEqual(reconciliation_facts(db,state,start=date(2020,1,1),end=date(2020,1,2)),[])
            for bounds in (dict(start=DAY),dict(end=DAY),dict(start=NOW.date(),end=DAY)):
                with self.assertRaises(SalesContractError): reconciliation_facts(db,state,**bounds)


    def test_ui_dynamics_restate_returns_and_preserve_personal_scope(self):
        overview = self.client.get('/sales/analytics/overview').json()
        self.assertEqual(len(overview['dynamics']), 31)
        day = next(r for r in overview['dynamics'] if r['date'] == str(DAY))
        self.assertEqual(Decimal(day['metrics']['revenue']['fact']), 280)
        self.assertEqual(sum(Decimal(r['metrics']['revenue']['fact']) for r in overview['dynamics']), 280)
        self.role(EmployeeRole.SELLER, seller=True)
        personal = self.client.get('/sales/analytics/me').json()
        self.assertNotIn('employee', str(personal)); self.assertNotIn('department', str(personal))
        self.assertEqual(personal['dynamics'], overview['dynamics'])

    def test_ui_product_names_category_checks_and_daily_values(self):
        self.ingest([self.row(DishName='Эклер', DishCategory='Десерты')])
        self.role(EmployeeRole.CHEF_CONFECTIONER)
        data = self.client.get('/sales/analytics/products').json()['products'][0]
        self.assertEqual(data['product_name'], 'Эклер')
        self.assertEqual(data['category'], 'Десерты')
        self.assertEqual(data['check_count'], 1)
        self.assertEqual(len(data['dynamics']), 1)
        self.assertEqual(Decimal(data['dynamics'][0]['revenue']), 280)
        self.assertNotIn('employee', str(data)); self.assertNotIn('raw_payload', str(data))

    def test_ui_freshness_safe_contract_role_matrix(self):
        allowed = {EmployeeRole.ADMIN, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR,
                   EmployeeRole.NETWORK_MANAGER, EmployeeRole.CHEF_CONFECTIONER,
                   EmployeeRole.HEAD_OF_PRODUCTION, EmployeeRole.SELLER}
        for role in EmployeeRole:
            self.role(role, seller=role == EmployeeRole.SELLER)
            result = self.client.get('/sales/analytics/status')
            self.assertEqual(result.status_code, 200 if role in allowed else 403)
            if role in allowed:
                self.assertNotIn('source_id', result.text)
                self.assertNotIn('error_code', result.text)
                self.assertIn('last_success_at', result.json())
        self.role(EmployeeRole.SELLER, seller=True)
        self.assertEqual(self.client.get('/sales/analytics/status?employee_id=other').status_code, 422)

    def test_ui_freshness_no_success_stale_and_failed(self):
        from app.sales.metrics import freshness
        with self.sessions() as db:
            state = source_state(db, 'eclair')
            state.last_success_at = None
            state.error_code = None
            self.assertTrue(freshness(state, NOW)['stale'])
            state.last_success_at = NOW - timedelta(minutes=29)
            self.assertFalse(freshness(state, NOW)['stale'])
            state.last_success_at = NOW - timedelta(minutes=31)
            state.error_code = 'PRIVATE_PROVIDER_ERROR'
            result = freshness(state, NOW)
            self.assertTrue(result['stale']); self.assertTrue(result['update_failed'])
            self.assertNotIn('PRIVATE_PROVIDER_ERROR', str(result))


    def test_ui_server_product_summary_category_filter_and_check_deduplication(self):
        self.ingest([self.row(DishName='Эклер', DishCategory='Десерты'),
                     self.row(DishName='Эклер', DishCategory='Десерты'),
                     self.row(DishId=str(uuid4()), DishName='Кофе', DishCategory='Напитки')])
        data = self.client.get('/sales/analytics/products?category=Десерты').json()
        self.assertEqual(data['categories'], ['Десерты', 'Напитки'])
        self.assertEqual(len(data['summaries']), 1)
        summary = data['summaries'][0]
        self.assertEqual(Decimal(summary['quantity']), 4)
        self.assertEqual(Decimal(summary['revenue']), 560)
        self.assertEqual(summary['check_count'], 1)
        self.assertEqual(Decimal(data['dynamics'][0]['revenue']), 560)
        self.assertIsNone(summary['department_id'])
        self.assertEqual(self.client.get('/sales/analytics/products?category=unknown').json()['summaries'], [])
        self.role(EmployeeRole.SELLER, seller=True)
        self.assertEqual(self.client.get('/sales/analytics/products?category=Десерты').status_code, 403)
