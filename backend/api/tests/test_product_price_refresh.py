"""Real price contract, date-only resolver and immutable refresh through outbox."""
import unittest
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from sqlalchemy import select, func
import httpx

from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.prices import PriceContext, PriceResponse
from app.integrations.iiko.exceptions import IikoContractError
from app.product_knowledge.price_resolver import resolve
from app.product_knowledge.price_refresh import SourcePriceSnapshot, PriceRefreshPayload, source_price_preview, publish_source_prices, collect_prices
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgePriceSnapshot as Snapshot
from app.models.audit import AuditEvent
from app.models.user import User
from tests import test_product_knowledge as k1
from tests.test_iiko_client import make_settings


def context(product, point, **changes):
    item=dict(dateFrom='2026-10-01', dateTo='2026-11-01', price='120.000001', included=True,
        documentId=str(uuid4()), schedule=None, includeForCategories=[], pricesForCategories=[])
    item.update(changes)
    return PriceContext(departmentId=point, productId=product, productSizeId=None, prices=[item])


class PriceReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_decimal_envelope_and_point_guard(self):
        product, point = uuid4(), uuid4(); calls=[]
        body={'result':'SUCCESS','errors':[],'revision':123,'response':[context(product,point).model_dump(mode='json')]}
        async def handler(request):
            calls.append(request)
            if request.url.path.endswith('/auth'): return httpx.Response(200,text='test-token')
            if request.url.path.endswith('/logout'): return httpx.Response(200,text='ok')
            return httpx.Response(200,json=body)
        async with IikoServerClient(make_settings(),transport=httpx.MockTransport(handler)) as client:
            result=await client.get_prices(date_from=date(2026,10,1),date_to=date(2026,11,1),department_id=point)
            self.assertEqual(result.contexts[0].prices[0].price,Decimal('120.000001'))
            body['response'][0]['departmentId']=str(uuid4())
            with self.assertRaises(IikoContractError):
                await client.get_prices(date_from=date(2026,10,1),date_to=date(2026,11,1),department_id=point)
            body['errors']=['failed']
            with self.assertRaises(IikoContractError):
                await client.get_prices(date_from=date(2026,10,1),date_to=date(2026,11,1),department_id=point)
        self.assertTrue(all(r.method=='GET' for r in calls))
        query=next(r.url.params for r in calls if r.url.path.endswith('/price'))
        self.assertEqual(query['includeOutOfSale'],'true');self.assertNotIn('type',query)

    def test_base_boundaries_exclusions_categories_and_schedule_ambiguity(self):
        product,point=uuid4(),uuid4();c=context(product,point,price=0,
            includeForCategories=[dict(categoryId=str(uuid4()),include=False)])
        self.assertEqual(resolve([c],date(2026,10,1))['price'].price,0)
        self.assertEqual(resolve([c],date(2026,11,1))['state'],'MISSING')
        excluded=context(product,point,price=None,included=False)
        self.assertEqual(resolve([excluded],date(2026,10,9))['state'],'EXCLUDED')
        future=context(product,point,dateFrom='2026-10-10')
        self.assertEqual(resolve([future],date(2026,10,9))['state'],'MISSING')
        self.assertEqual(resolve([c,c],date(2026,10,9))['state'],'CONFLICT')
        timed=context(product,point,schedule={'periods':[{'begin':'16:00','end':'17:00','daysOfWeek':[5]}]})
        self.assertEqual(resolve([c,timed],date(2026,10,9))['state'],'TIME_DEPENDENT')
        self.assertEqual(resolve([c,timed],date(2026,10,8))['state'],'CONFIRMED')
        timed.prices[0].schedule={'periods':[{'begin':'22:00','end':'02:00','daysOfWeek':[5]}]}
        self.assertEqual(resolve([c,timed],date(2026,10,8))['state'],'TIME_DEPENDENT')


class PriceRefreshTests(unittest.IsolatedAsyncioTestCase):
    row=k1.ProductKnowledgeTests.row
    ingest=k1.ProductKnowledgeTests.ingest
    plan=k1.ProductKnowledgeTests.plan
    load=k1.ProductKnowledgeTests.load
    tearDown=k1.ProductKnowledgeTests.tearDown

    def setUp(self):
        k1.ProductKnowledgeTests.setUp(self);self.load()
        with self.sessions() as db:
            products={str(p.iiko_product_id):dict(id=str(p.id),unit_id=str(p.unit_id),unit_name=p.unit_name) for p in db.scalars(select(Product))}
        self.data=SourcePriceSnapshot(source_id=self.source_id,confirmed_point_ids=[self.department_id],currency='RUB',
            office_evidence='Office control fixture',observed_at=datetime(2026,10,9,tzinfo=timezone.utc),
            date_from='2026-10-01',date_to='2026-11-01',products=products,
            point_links={str(self.department_id):str(self.point)},revisions={str(self.department_id):123},
            contexts=[context(self.product,self.point)])

    def store(self,snapshot=None):
        snapshot=snapshot or self.data
        with self.sessions.begin() as db:
            report=source_price_preview(db,'eclair',snapshot)
            return publish_source_prices(db,'eclair',snapshot,expected_hash=report['plan_hash'],actor=db.get(User,1)).id

    async def test_retry_correction_removed_price_and_local_verification_preserved(self):
        with self.sessions.begin() as db:
            p=db.scalar(select(Product).where(Product.iiko_product_id==self.product));pid=p.id
            p.local_name='Ручное имя';p.sale_status='OFF_SALE';p.verified_at=datetime(2026,10,9,tzinfo=timezone.utc);p.version=7
        first=self.store();self.assertEqual(self.store(),first)
        url=f'/products/{pid}?department_id={self.department_id}&price_at=2026-10-09'
        self.assertEqual(Decimal(self.client.get(url).json()['price']['amount']),Decimal('120.000001'))
        changed=self.data.model_copy(deep=True);changed.observed_at+=timedelta(hours=1);changed.contexts[0].prices[0].price=Decimal('150')
        self.store(changed);self.assertEqual(Decimal(self.client.get(url).json()['price']['amount']),150)
        missing=changed.model_copy(deep=True);missing.observed_at+=timedelta(hours=1);missing.contexts=[]
        self.store(missing);result=self.client.get(url).json();self.assertIsNone(result['price'])
        self.assertEqual((result['name'],result['sale_status'],result['version']),('Ручное имя','OFF_SALE',7));self.assertTrue(result['verified_at'])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),3)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type=='PRODUCT_KNOWLEDGE_PRICES_REFRESHED')),3)

    async def test_changed_scope_audit_failure_and_tampered_hash(self):
        from app.product_knowledge.bootstrap import PublicationError
        with self.sessions.begin() as db:
            with self.assertRaisesRegex(PublicationError,'REVIEW_REQUIRED'):
                publish_source_prices(db,'eclair',self.data,expected_hash='bad',actor=db.get(User,1))
        with patch('app.product_knowledge.price_refresh.record_audit_event',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.store()
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),0)
        with self.sessions.begin() as db:
            db.scalar(select(Product)).published=False
        with self.assertRaisesRegex(PublicationError,'SCOPE_CHANGED'):self.store()

    async def test_scheduler_outbox_reuses_local_executor_and_safe_claim(self):
        from tests.test_sales_schedule_ui import SalesScheduleUiTests
        from app.automation.scheduler import run_scheduler_once
        from app.automation.outbox import OutboxWorker, SqlAlchemyOutboxStore, DeliveryStatus
        from app.automation.local_actions import LocalAutomationActionExecutor
        from app.models.automation import AutomationSchedule
        with SalesScheduleUiTests.client(self) as client:
            body=dict(name='Цены продукции',automation_type='products.sync_iiko_prices',scope_type='company',scope_id=None,
                schedule_config={'type':'interval','minutes':60},payload=self.data.model_dump(mode='json',include={'source_id','confirmed_point_ids','currency','office_evidence'}),
                recipients=[],timezone='Asia/Yekaterinburg',is_enabled=True)
            response=client.post('/automation/schedules',json=body);self.assertEqual(response.status_code,201,response.text)
            schedule_id=response.json()['id']
        with self.sessions() as db:scheduled=db.get(AutomationSchedule,schedule_id).next_run_at.replace(tzinfo=timezone.utc)
        provider=AsyncMock()
        worker=OutboxWorker(store=SqlAlchemyOutboxStore(self.sessions),provider=provider,worker_id='price-test',
            callback_url='http://unused.invalid',local_executor=LocalAutomationActionExecutor(self.sessions))
        with patch('app.product_knowledge.price_refresh.collect_prices',new=AsyncMock(return_value=self.data)):
            self.assertEqual(run_scheduler_once(self.sessions,now=scheduled).created,1)
            from app.models.automation import AutomationExecution, OutboxEvent
            with self.sessions() as db:
                execution=db.scalar(select(AutomationExecution));event=db.scalar(select(OutboxEvent))
                self.assertEqual(execution.payload,body['payload']);self.assertEqual(event.payload,body['payload'])
                self.assertEqual(execution.schedule_id,schedule_id)
            self.assertEqual((await worker.process_one()).status,DeliveryStatus.PUBLISHED)
        provider.send_command.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),1)
            self.assertEqual(db.get(AutomationSchedule,schedule_id).next_run_at.replace(tzinfo=timezone.utc),scheduled+timedelta(minutes=60))

    async def test_collection_is_bounded_existing_ids_only_and_unit_changes_fail(self):
        mock=AsyncMock();mock.__aenter__.return_value=mock
        mock.get_products.return_value=[SimpleNamespace(dto=SimpleNamespace(external_id=pid,base_unit_external_id=p['unit_id'])) for pid,p in self.data.products.items()]
        mock.get_units.return_value=[SimpleNamespace(dto=SimpleNamespace(external_id=self.unit,name='шт'))]
        mock.get_prices.return_value=PriceResponse(revision=123,contexts=[context(self.product,self.point),context(uuid4(),self.point)])
        payload=PriceRefreshPayload.model_validate(self.data.model_dump(include={'source_id','confirmed_point_ids','currency','office_evidence'}))
        with patch('app.product_knowledge.price_refresh.source_identity',return_value=self.source_id), patch('app.product_knowledge.price_refresh.IikoServerClient',return_value=mock):
            snapshot=await collect_prices(self.sessions,tenant_id='eclair',payload=payload,now=self.data.observed_at)
            self.assertEqual(len(snapshot.contexts),1);self.assertEqual(len(snapshot.products),2)
            self.assertEqual((snapshot.date_to-snapshot.date_from).days,63)
            mock.get_prices.assert_awaited_once()
            mock.get_units.return_value=[SimpleNamespace(dto=SimpleNamespace(external_id=self.unit,name='кг'))]
            from app.product_knowledge.bootstrap import PublicationError
            with self.assertRaisesRegex(PublicationError,'UNIT_MISMATCH'):
                await collect_prices(self.sessions,tenant_id='eclair',payload=payload,now=self.data.observed_at)

    async def test_late_old_revision_cannot_replace_newer_prices(self):
        self.store()
        older=self.data.model_copy(deep=True);older.observed_at+=timedelta(hours=1)
        older.revisions={str(self.department_id):122}
        from app.product_knowledge.bootstrap import PublicationError
        with self.assertRaisesRegex(PublicationError,'REVISION_STALE'):
            self.store(older)

    async def test_health_stale_failure_recovery_and_point_tenant_isolation(self):
        from app.product_knowledge.service import price_health
        from app.models.automation import AutomationExecution, ExecutionStatus
        from app.models.supply import Department
        self.store()
        now = self.data.observed_at + timedelta(hours=3)
        with self.sessions.begin() as db:
            actor = db.get(User, 1); point = db.get(Department, self.department_id)
            status = price_health(db, actor, self.source_id, [point], now=now)[0]
            self.assertTrue(status['stale']); self.assertFalse(status['update_failed'])
            self.assertEqual(status['last_success_at'], self.data.observed_at)
            for tenant, points in [('other', [str(point.id)]), ('eclair', [str(uuid4())])]:
                db.add(AutomationExecution(tenant_id=tenant, automation_type='products.sync_iiko_prices',
                    scope_type='company', requested_at=now, finished_at=now, status=ExecutionStatus.FAILED,
                    payload={'source_id':self.source_id, 'confirmed_point_ids':points}))
            db.flush()
            self.assertFalse(price_health(db, actor, self.source_id, [point], now=now)[0]['update_failed'])
            db.add(AutomationExecution(tenant_id='eclair', automation_type='products.sync_iiko_prices',
                scope_type='company', requested_at=now, finished_at=now, status=ExecutionStatus.FAILED,
                payload={'source_id':self.source_id, 'confirmed_point_ids':[str(point.id)]}, error_message='private error'))
            db.flush()
            status = price_health(db, actor, self.source_id, [point], now=now)[0]
            self.assertTrue(status['update_failed']); self.assertEqual(status['last_success_at'], self.data.observed_at)
            self.assertNotIn('error_message', status)
        recovered = self.data.model_copy(deep=True); recovered.observed_at = now + timedelta(minutes=1)
        self.store(recovered)
        with self.sessions() as db:
            status = price_health(db, db.get(User,1), self.source_id, [db.get(Department,self.department_id)], now=recovered.observed_at)[0]
            self.assertFalse(status['stale']); self.assertFalse(status['update_failed'])
        with self.sessions() as db: pid = db.scalar(select(Product.id))
        body = self.client.get(f'/products/{pid}?price_at=2026-10-09').json()
        self.assertEqual(body['price_health'][0]['last_success_at'], recovered.observed_at.isoformat().replace('+00:00','Z'))

    async def test_ui_configuration_create_saved_payload_duplicate_and_edit(self):
        from tests.test_sales_schedule_ui import SalesScheduleUiTests
        self.store()
        with SalesScheduleUiTests.client(self) as client:
            config = client.get('/automation/product-price-configuration')
            self.assertEqual(config.status_code,200,config.text)
            policy = config.json()['payload']
            self.assertEqual(policy['confirmed_point_ids'],[str(self.department_id)])
            self.assertEqual(policy['source_id'],self.source_id)
            self.assertEqual(policy['currency'],'RUB'); self.assertEqual(policy['office_evidence'],self.data.office_evidence)
            body=dict(name='Цены',automation_type='products.sync_iiko_prices',scope_type='company',scope_id=None,
                schedule_config={'type':'interval','minutes':60},payload=policy,recipients=[],timezone='Asia/Yekaterinburg',is_enabled=True)
            missing=client.post('/automation/schedules',json={**body,'payload':{}})
            self.assertEqual(missing.status_code,422)
            created=client.post('/automation/schedules',json=body)
            self.assertEqual(created.status_code,201,created.text)
            self.assertEqual(created.json()['payload'],policy)
            duplicate=client.post('/automation/schedules',json=body)
            self.assertEqual(duplicate.status_code,422); self.assertIn('уже существует',duplicate.json()['detail'])
            sid=created.json()['id']
            self.assertEqual(client.patch(f'/automation/schedules/{sid}',json={'name':'Цены обновлённые'}).status_code,200)
            self.assertEqual(client.get(f'/automation/schedules/{sid}').json()['payload'],policy)

    async def test_manual_price_run_creates_execution_outbox_and_uses_same_worker(self):
        from tests.test_sales_schedule_ui import SalesScheduleUiTests
        from app.models.automation import AutomationExecution, OutboxEvent, ExecutionStatus
        from app.automation.outbox import OutboxWorker, SqlAlchemyOutboxStore, DeliveryStatus
        from app.automation.local_actions import LocalAutomationActionExecutor
        from app.automation.catalog import require_available_automation_type
        policy=self.data.model_dump(mode='json',include={'source_id','confirmed_point_ids','currency','office_evidence'})
        with SalesScheduleUiTests.client(self) as client:
            created=client.post('/automation/schedules',json=dict(name='Цены ручной запуск',automation_type='products.sync_iiko_prices',scope_type='company',scope_id=None,
                schedule_config={'type':'interval','minutes':60},payload=policy,recipients=[],timezone='Asia/Yekaterinburg',is_enabled=True))
            self.assertEqual(created.status_code,201,created.text);sid=created.json()['id'];next_run=created.json()['next_run_at']
            response=client.post(f'/automation/schedules/{sid}/run')
            self.assertEqual(response.status_code,201,response.text)
            self.assertEqual(response.json()['status'],'pending')
            self.assertEqual(client.get(f'/automation/schedules/{sid}').json()['next_run_at'].removesuffix('Z'),next_run.removesuffix('Z'))
        self.assertTrue(require_available_automation_type('products.sync_iiko_prices').supports_manual_run)
        with self.sessions() as db:
            execution=db.scalar(select(AutomationExecution));event=db.scalar(select(OutboxEvent))
            self.assertEqual(execution.payload,policy);self.assertEqual(event.payload,policy)
            self.assertEqual(execution.schedule_id,sid);self.assertEqual(event.execution_id,execution.execution_id)
        provider=AsyncMock()
        worker=OutboxWorker(store=SqlAlchemyOutboxStore(self.sessions),provider=provider,worker_id='price-manual-test',
            callback_url='http://unused.invalid',local_executor=LocalAutomationActionExecutor(self.sessions))
        with patch('app.product_knowledge.price_refresh.collect_prices',new=AsyncMock(return_value=self.data)):
            self.assertEqual((await worker.process_one()).status,DeliveryStatus.PUBLISHED)
        provider.send_command.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(AutomationExecution)).status,ExecutionStatus.SUCCEEDED)
            self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),1)

    async def test_manual_price_run_invalid_saved_payload_scope_interval_disabled_and_permissions(self):
        from tests.test_sales_schedule_ui import SalesScheduleUiTests
        from app.models.automation import AutomationSchedule, AutomationExecution, OutboxEvent
        from app.api.dependencies import get_current_admin, get_current_user
        from app.models.employee import EmployeeRoleAssignment
        policy=self.data.model_dump(mode='json',include={'source_id','confirmed_point_ids','currency','office_evidence'})
        with SalesScheduleUiTests.client(self) as client:
            created=client.post('/automation/schedules',json=dict(name='Цены проверки',automation_type='products.sync_iiko_prices',scope_type='company',scope_id=None,
                schedule_config={'type':'interval','minutes':60},payload=policy,recipients=[],timezone='Asia/Yekaterinburg',is_enabled=True))
            sid=created.json()['id']
            for changes in [dict(payload={}),dict(scope_type='department',scope_id='wrong'),dict(schedule_config={'type':'interval','minutes':15})]:
                with self.sessions.begin() as db:
                    schedule=db.get(AutomationSchedule,sid)
                    schedule.payload=policy;schedule.scope_type='company';schedule.scope_id=None;schedule.schedule_config={'type':'interval','minutes':60}
                    for key,value in changes.items():setattr(schedule,key,value)
                rejected=client.post(f'/automation/schedules/{sid}/run')
                self.assertEqual(rejected.status_code,422,rejected.text)
                self.assertRegex(rejected.json()['detail'],'Регламент цен должен|Параметры регламента цен')
            with self.sessions.begin() as db:db.get(AutomationSchedule,sid).is_enabled=False
            self.assertEqual(client.post(f'/automation/schedules/{sid}/run').status_code,409)
            # Real ActionContext dependency rejects a non-admin role before dispatch.
            client.app.dependency_overrides.pop(get_current_admin)
            def actor():
                with self.sessions() as db:return db.get(User,1)
            client.app.dependency_overrides[get_current_user]=actor
            with self.sessions.begin() as db:
                for role in db.scalars(select(EmployeeRoleAssignment).where(EmployeeRoleAssignment.tenant_id=='eclair')):
                    role.role='SELLER'
            self.assertEqual(client.post(f'/automation/schedules/{sid}/run').status_code,403)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AutomationExecution)),0)
            self.assertEqual(db.scalar(select(func.count()).select_from(OutboxEvent)),0)
