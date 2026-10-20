"""R-M2 policy and full local API/Core/snapshot/source authorization path."""
import asyncio, copy, unittest
from datetime import datetime, timezone, date, timedelta
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from sqlalchemy import select, func, MetaData, JSON, BigInteger, Integer
from sqlalchemy.dialects.postgresql import JSONB
from tests import test_raw_materials as fixture
from app.models.automation import AutomationSchedule, AutomationExecution as Execution, OutboxEvent
from app.models.iiko import IikoProductMapping, IikoUnitMapping
from app.models.raw_material import MaterialPurchaseSnapshot as Snapshot
from app.models.user import User
from app.models.employee import EmployeeRole
from app.automation.local_actions import LocalAutomationActionExecutor
from app.automation.outbox import SqlAlchemyOutboxStore, OutboxClaimLostError
from app.raw_materials import purchase_refresh as refresh
from app.raw_materials.purchases import evaluate, parse_export, windows, SOURCE, WAREHOUSE, TECHNICAL
from app.product_knowledge.bootstrap import digest
from fastapi import HTTPException

SUPPLIERS={'supplier':dict(name='Внешний поставщик',is_supplier=True,is_employee=False,represents_store=False,is_deleted=False)}


def document(product='product',unit='unit',**changes):
    row=dict(id=str(uuid4()),documentNumber='ПН-42',status='PROCESSED',dateIncoming='2026-10-18T09:00:00',supplier='supplier',defaultStore=WAREHOUSE,
        items=[dict(num='1',product=product,amount='3',actualAmount='3',amountUnit=unit,sum='100',price='33.33',vatPercent='20',vatSum='16.67')])
    row.update(changes); row['source_hash']=digest(row); return row


class PurchasePolicyTests(unittest.TestCase):
    def evaluate(self, rows, suppliers=None):
        return evaluate(rows, suppliers if suppliers is not None else SUPPLIERS,dict(iiko_product_id='product',unit_id='unit',unit='кг'),date_from='2026-04-01',date_to='2026-10-21')

    def test_exact_sum_aggregation_duplicates_and_newer_conflict(self):
        row=document(); result=self.evaluate([row,copy.deepcopy(row)])
        self.assertEqual(result['amount'],'33.333333333333333333333333333333333333');self.assertEqual(len(result['candidates']),1)
        item=copy.deepcopy(row['items'][0]);item.update(num='2',amount='1',actualAmount='1',sum='50');row['items'].append(item)
        self.assertEqual(self.evaluate([row])['amount'],'37.5')
        self.assertIn('LATEST_DOCUMENT_CONFLICT',self.evaluate([document(),document()])['reasons'])
        revision=copy.deepcopy(row);revision['source_hash']='changed'
        self.assertIn('DOCUMENT_REVISION_CONFLICT',self.evaluate([row,revision])['reasons'])

    def test_newer_uncertain_blocks_no_fallback(self):
        older=document(dateIncoming='2026-10-17T09:00:00')
        for key,value,reason in [('amountUnit','PCS','UNIT_MISMATCH'),('sum','0','AMOUNT_UNCONFIRMED'),('sum','NaN','AMOUNT_UNCONFIRMED'),('actualAmount','2','AMOUNT_UNCONFIRMED'),('vatSum',None,'TAX_UNCONFIRMED'),('num',None,'LINE_IDENTITY_CONFLICT'),('num','','LINE_IDENTITY_CONFLICT'),('containerId',str(uuid4()),'CONTAINER_UNCONFIRMED'),('isAdditionalExpense','true','ADDITIONAL_EXPENSE')]:
            row=document();row['items'][0][key]=value;result=self.evaluate([older,row])
            self.assertEqual(result['status'],'BLOCKED',key);self.assertIsNone(result['amount']);self.assertIn(reason,result['reasons'])
        previous=document(dateIncoming='2026-05-01T09:00:00');previous['items'][0]['amountUnit']='PCS'
        self.assertIn('MIXED_UNITS_BLOCKED',self.evaluate([previous,document()])['reasons'])
        self.assertEqual(self.evaluate([document(dateIncoming='')])['status'],'BLOCKED')
        self.assertEqual(self.evaluate([document(dateIncoming='2026-03-01T01:00:00')])['status'],'NO_DATA')

    def test_exclusions_external_supplier_warehouse_and_currency(self):
        for flags in [dict(is_employee=True),dict(is_deleted=True),dict(is_supplier=False)]:
            suppliers=copy.deepcopy(SUPPLIERS);suppliers['supplier'].update(flags)
            self.assertIn('SUPPLIER_UNCONFIRMED',self.evaluate([document()],suppliers)['reasons'])
        self.assertEqual(self.evaluate([document()],{})['status'],'BLOCKED')
        suppliers=copy.deepcopy(SUPPLIERS);suppliers['supplier']['represents_store']=True
        self.assertEqual(self.evaluate([document()],suppliers)['status'],'NO_DATA')
        for status in ['NEW','CANCELLED','DELETED']:self.assertEqual(self.evaluate([document(status=status)])['status'],'NO_DATA')
        self.assertEqual(self.evaluate([document(id=TECHNICAL)])['status'],'NO_DATA')
        self.assertEqual(self.evaluate([document(documentNumber='EOS-REAL-42')])['status'],'READY')
        row=document(defaultStore=str(uuid4()));self.assertEqual(self.evaluate([row])['status'],'NO_DATA')
        row['items'][0]['store']=WAREHOUSE;self.assertEqual(self.evaluate([row])['status'],'READY')
        for changes in [dict(defaultStore=None),dict(defaultStore='invalid'),dict(currency='USD')]:self.assertEqual(self.evaluate([document(**changes)])['status'],'BLOCKED')

    def test_completeness_windows_and_schedule_gate(self):
        self.assertEqual(list(windows(date(2026,10,20)))[0],(date(2026,4,1),date(2026,5,1)))
        self.assertEqual(list(windows(date(2026,10,20)))[-1][1],date(2026,10,21))
        self.assertEqual(parse_export('<incomingInvoiceDtoes/>'),[])
        for xml in ['<error/>','<incomingInvoiceDtoes><document><id>bad</id></document></incomingInvoiceDtoes>','<incomingInvoiceDtoes><hasMore>true</hasMore></incomingInvoiceDtoes>']:
            with self.assertRaises(ValueError):parse_export(xml)
        from app.schemas.automation import validate_automation_schedule_contract, DailyScheduleConfig
        with self.assertRaisesRegex(ValueError,'manual'):validate_automation_schedule_contract(refresh.ACTION,DailyScheduleConfig(type='daily',time='06:00'),{})


class PurchaseFlowTests(unittest.TestCase):
    seed=fixture.RawMaterialTests.seed
    bind_client=fixture.RawMaterialTests.bind_client
    enroll=fixture.RawMaterialTests.enroll
    role=fixture.RawMaterialTests.role
    tearDown=fixture.RawMaterialTests.tearDown
    def setUp(self):
        fixture.RawMaterialTests.setUp(self)
        metadata=MetaData();User.__table__.to_metadata(metadata)
        for model in (AutomationSchedule,Execution,OutboxEvent):
            table=model.__table__.to_metadata(metadata)
            for column in table.columns:
                if isinstance(column.type,JSONB):column.type=JSON();column.server_default=None
                if column.primary_key and isinstance(column.type,BigInteger):column.type=Integer()
            table.create(self.engine,checkfirst=True)
        IikoProductMapping.__table__.create(self.engine);self.enroll();self.path='/raw-materials/'+str(self.product)
        with self.sessions.begin() as db:
            unit=db.scalar(select(IikoUnitMapping));self.source_product=uuid4();self.source_unit=unit.iiko_unit_id
            db.add(IikoProductMapping(tenant_id=self.tenant,iiko_product_id=self.source_product,eos_product_id=self.product,status='CONFIRMED',source_name='Сливки',source_unit_id=self.source_unit,is_deleted=False))
    def request(self,request_id=None):return self.client.post(self.path+'/metrics/refresh',json=dict(request_id=str(request_id or uuid4())))
    def claim(self):return SqlAlchemyOutboxStore(self.sessions).claim_next(worker_id='rm2-test',claimed_at=datetime.now(timezone.utc)+timedelta(seconds=1))
    def snapshot(self,claim):
        result=evaluate([document(str(self.source_product),str(self.source_unit))],SUPPLIERS,claim.payload['mapping'],date_from='2026-04-01',date_to='2026-10-21')
        return dict(product_id=str(self.product),source_id=SOURCE,mapping=claim.payload['mapping'],policy='fixture',observed_at=datetime.now(timezone.utc).isoformat(),manifest=[],result=result)
    def run_claim(self,claim,snapshot=None):
        with patch.object(refresh,'collect',AsyncMock(return_value=snapshot or self.snapshot(claim))):return asyncio.run(LocalAutomationActionExecutor(self.sessions).execute(claim,executed_at=datetime.now(timezone.utc)))

    def test_full_flow_idempotency_retry_failure_preserves_history(self):
        request_id=uuid4();response=self.request(request_id);self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(self.request(request_id).status_code,202);self.assertEqual(self.request().status_code,202)
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Execution)),1)
        claim=self.claim();snapshot=self.snapshot(claim);result=self.run_claim(claim,snapshot)
        self.assertEqual(result['quality'],'READY');self.assertEqual(self.client.get(self.path).json()['last_purchase_price']['status'],'READY')
        response=self.client.get(self.path+'/metrics/'+result['snapshot_id']+'/sources');self.assertEqual(response.status_code,200);self.assertIn('ПН-42',response.text)
        with self.sessions.begin() as db:
            refresh.publish(db,self.tenant,snapshot,execution_id=claim.execution_id)
            self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),1)
        with self.assertRaises(OutboxClaimLostError):self.run_claim(claim,snapshot)
        self.assertEqual(self.request().status_code,202);claim=self.claim()
        with patch.object(refresh,'collect',AsyncMock(side_effect=TimeoutError)):
            with self.assertRaises(TimeoutError):asyncio.run(LocalAutomationActionExecutor(self.sessions).execute(claim,executed_at=datetime.now(timezone.utc)))
        self.assertEqual(self.client.get(self.path).json()['last_purchase_price']['status'],'READY')

    def test_money_roles_sources_history_refresh_sort_and_tenant(self):
        self.request();result=self.run_claim(self.claim());money={'ADMIN','SUPPLY_MANAGER','DIRECTOR','DEPUTY_DIRECTOR','ACCOUNTANT'}
        for role in EmployeeRole:
            self.role(role.value)
            for path in ['/metrics','/metrics/'+result['snapshot_id']+'/sources']:
                response=self.client.get(self.path+path);self.assertEqual(response.status_code,200 if role.value in money else 403,(role,response.text))
                if role.value not in money:self.assertNotIn('33.333',response.text)
            self.assertEqual(self.request().status_code,202 if role.value in money else 403,role)
            if role.value not in money:self.assertNotIn('last_purchase_price',self.client.get(self.path).text)
        self.role('ADMIN')
        self.assertEqual(self.client.get('/raw-materials/'+str(self.foreign)+'/metrics').status_code,404)
        self.assertEqual(self.client.get('/raw-materials/'+str(self.second)+'/metrics/'+result['snapshot_id']+'/sources').status_code,404)
        self.assertEqual(self.client.get('/raw-materials?sort=last_purchase_price').status_code,422)
        self.assertEqual(self.client.post(self.path+'/metrics/refresh',json=dict(request_id=str(uuid4()),amount='98765')).status_code,422)

    def test_lost_claim_and_changed_mapping_no_publication(self):
        self.request();claim=self.claim();snapshot=self.snapshot(claim)
        with self.sessions.begin() as db:db.get(OutboxEvent,claim.id).locked_by='other-worker'
        with self.assertRaises(OutboxClaimLostError):self.run_claim(claim,snapshot)
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),0)
        with self.sessions.begin() as db:
            db.get(OutboxEvent,claim.id).locked_by=claim.lock_token;db.scalar(select(IikoProductMapping)).status='UNMAPPED'
        with self.assertRaises(HTTPException):self.run_claim(claim,snapshot)
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),0)

    def test_collection_through_existing_client_outside_db_and_complete_manifest(self):
        from types import SimpleNamespace
        import xml.etree.ElementTree as ET
        row=document(str(self.source_product),str(self.source_unit))
        root=ET.Element('incomingInvoiceDtoes');doc=ET.SubElement(root,'document')
        for key,value in row.items():
            if key not in {'items','source_hash'}:ET.SubElement(doc,key).text=value
        items=ET.SubElement(doc,'items')
        for line in row['items']:
            item=ET.SubElement(items,'item')
            for key,value in line.items():ET.SubElement(item,key).text=value
        calls=[]
        class Client:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def get_products(inner):return [SimpleNamespace(dto=SimpleNamespace(external_id=self.source_product,is_deleted=False,base_unit_external_id=self.source_unit))]
            async def get_units(inner):return [SimpleNamespace(dto=SimpleNamespace(external_id=self.source_unit,name='кг'))]
            async def get_suppliers(inner):return [SimpleNamespace(external_id='supplier',model_dump=lambda **kw:SUPPLIERS['supplier'])]
            async def get_raw_material_invoice_export(inner,**bounds):
                calls.append(bounds)
                return ET.tostring(root,encoding='unicode') if bounds['date_from'].month==10 else '<incomingInvoiceDtoes/>'
        self.request();claim=self.claim()
        with patch.object(refresh,'get_iiko_settings',return_value=object()),patch.object(refresh,'source_identity',return_value=SOURCE),patch.object(refresh,'IikoServerClient',return_value=Client()):
            result=asyncio.run(LocalAutomationActionExecutor(self.sessions).execute(claim,executed_at=datetime(2026,10,20,tzinfo=timezone.utc)))
        self.assertEqual(result['quality'],'READY');self.assertEqual(len(calls),7)
        self.assertEqual(calls[-1]['date_to'],date(2026,10,20))
        response=self.client.get(self.path+'/metrics/'+result['snapshot_id']+'/sources').json()
        self.assertEqual(len(response['manifest']),7);self.assertTrue(response['hash'])

    def test_core_worker_retries_error_and_publishes_once_without_provider(self):
        from app.automation.outbox import OutboxWorker,DeliveryStatus
        from app.models.automation import ExecutionStatus
        self.request()
        with self.sessions() as db:
            execution=db.scalar(select(Execution));payload=execution.payload
        class Claim:
            pass
        claim=Claim();claim.payload=payload
        snapshot=self.snapshot(claim)
        now=datetime.now(timezone.utc)+timedelta(seconds=1)
        provider=AsyncMock()
        worker=OutboxWorker(store=SqlAlchemyOutboxStore(self.sessions),provider=provider,worker_id='rm2-worker',callback_url='https://example.invalid/callback',clock=lambda:now,local_executor=LocalAutomationActionExecutor(self.sessions))
        with patch.object(refresh,'collect',AsyncMock(side_effect=TimeoutError)):
            outcome=asyncio.run(worker.process_one())
        self.assertEqual(outcome.status,DeliveryStatus.RETRY_SCHEDULED)
        with self.sessions() as db:
            execution=db.scalar(select(Execution));self.assertEqual(execution.status,ExecutionStatus.RETRYING)
            now=execution.next_retry_at.replace(tzinfo=timezone.utc)+timedelta(seconds=1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),0)
        with patch.object(refresh,'collect',AsyncMock(return_value=snapshot)):
            self.assertEqual(asyncio.run(worker.process_one()).status,DeliveryStatus.PUBLISHED)
        self.assertEqual(asyncio.run(worker.process_one()).status,DeliveryStatus.NO_EVENT)
        provider.publish.assert_not_awaited()
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),1)

    def test_provider_callback_cannot_finalize_local_purchase(self):
        from app.api.routes.automation import router,require_callback_token
        self.client.app.include_router(router)
        self.client.app.dependency_overrides[require_callback_token]=lambda:None
        self.request()
        with self.sessions() as db:execution=db.scalar(select(Execution));eid=execution.execution_id
        response=self.client.post('/automation/callback',json=dict(execution_id=str(eid),status='succeeded',result={'amount':'fake'}))
        self.assertEqual(response.status_code,409,response.text)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(Execution)).status,'pending')
            self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot)),0)
