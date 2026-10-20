"""Exact source grants, withdrawal, unchanged history and financially isolated API/Core flow."""
import copy
import unittest
from datetime import date
from unittest.mock import patch
from uuid import UUID, uuid4
from tests import test_material_purchases as fixture
from sqlalchemy import select, func
from app.models.raw_material import MaterialDocumentAdmission as Decision, MaterialPurchaseSnapshot as Snapshot
from app.models.audit import AuditEvent
from app.models.employee import EmployeeRole
from app.models.user import User
from app.raw_materials import admissions, purchase_refresh as refresh
from app.raw_materials.admission_policy import line_hash
from app.raw_materials.purchases import evaluate, WAREHOUSE
from app.raw_materials.analytics import average


def grant(doc,kind='EMPLOYEE_PURCHASE',line_num='',**changes):
    value=dict(id=str(uuid4()),kind=kind,document_id=doc['id'],document_hash=doc['source_hash'],line_num=line_num,line_hash=line_hash(doc['items'][0]) if line_num else '',verification={})
    value.update(changes);return value


class AdmissionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.doc=fixture.document();self.mapping=dict(iiko_product_id='product',unit_id='unit',unit='кг')
        self.suppliers=copy.deepcopy(fixture.SUPPLIERS);self.suppliers['supplier']['is_employee']=True
    def run_policy(self,docs=None):
        return evaluate(docs or [self.doc],self.suppliers,self.mapping,date_from='2026-04-01',date_to='2026-11-01')
    def test_default_exact_document_hash_and_line_scope(self):
        self.assertEqual(self.run_policy()['status'],'BLOCKED')
        self.mapping['document_admissions']=[grant(self.doc)]
        self.assertEqual(self.run_policy()['status'],'READY')
        other=fixture.document();self.assertEqual(self.run_policy([other])['status'],'BLOCKED')
        changed=copy.deepcopy(self.doc);changed['source_hash']='changed';self.assertEqual(self.run_policy([changed])['status'],'BLOCKED')
        self.mapping['document_admissions']=[grant(self.doc,line_num='1')]
        self.assertEqual(self.run_policy()['status'],'READY')
        second=copy.deepcopy(self.doc);second['items'].append(dict(second['items'][0],num='2'))
        self.assertEqual(self.run_policy([second])['status'],'BLOCKED')
        second=copy.deepcopy(self.doc);second['items'][0]['sum']='200';self.assertEqual(self.run_policy([second])['status'],'BLOCKED')
    def test_admission_never_overrides_other_quality_or_conversions(self):
        self.mapping['document_admissions']=[grant(self.doc)]
        for flags in (dict(is_supplier=False),dict(is_deleted=True)):
            self.suppliers['supplier'].update(flags);self.assertEqual(self.run_policy()['status'],'BLOCKED');self.suppliers['supplier'].update(is_supplier=True,is_deleted=False)
        for field,value in [('amountUnit','PCS'),('actualAmount','2'),('vatSum',None)]:
            bad=copy.deepcopy(self.doc);bad['items'][0][field]=value;self.assertEqual(self.run_policy([bad])['status'],'BLOCKED')
        self.assertEqual(self.run_policy([dict(self.doc,status='NEW')])['status'],'NO_DATA')
    def test_base_unit_container_requires_separate_exact_proof_without_conversion(self):
        self.doc['items'][0]['containerId']=str(uuid4())
        employee=grant(self.doc);self.mapping['document_admissions']=[employee]
        self.assertEqual(self.run_policy()['status'],'BLOCKED')
        packaging=grant(self.doc,'BASE_UNIT_CONTAINER','1',verification=dict(unit_id='unit',quantity='3',container_id=self.doc['items'][0]['containerId']))
        self.mapping['document_admissions'].append(packaging)
        result=self.run_policy();self.assertEqual(result['status'],'READY');line=result['candidates'][0]['lines'][0]
        self.assertEqual(line['containerId'],self.doc['items'][0]['containerId']);self.assertEqual(line['actualAmount'],'3');self.assertIsNone(line['conversion']);self.assertEqual(len(line['document_admissions']),2)
        for key,value in [('quantity','30'),('unit_id','PCS'),('container_id',str(uuid4()))]:
            old=packaging['verification'][key];packaging['verification'][key]=value;self.assertEqual(self.run_policy()['status'],'BLOCKED');packaging['verification'][key]=old
        self.doc['items'][0]['amountUnit']='PCS';self.assertEqual(self.run_policy()['status'],'BLOCKED')
    def test_average_has_no_implicit_employee_exception(self):
        self.doc['dateIncoming']='2026-06-08T09:00:00'
        before=average([self.doc],self.suppliers,self.mapping,start=date(2026,4,1),end=date(2026,10,1),units={})
        self.assertEqual(before['status'],'BLOCKED');self.assertIsNone(before['amount'])
        self.mapping['document_admissions']=[grant(self.doc)]
        after=average([self.doc],self.suppliers,self.mapping,start=date(2026,4,1),end=date(2026,10,1),units={})
        self.assertEqual(after['status'],'READY');self.assertEqual(after['denominator'],'3')


class AdmissionFlowTests(unittest.TestCase):
    setUp=fixture.PurchaseFlowTests.setUp
    seed=fixture.PurchaseFlowTests.seed
    bind_client=fixture.PurchaseFlowTests.bind_client
    enroll=fixture.PurchaseFlowTests.enroll
    role=fixture.PurchaseFlowTests.role
    tearDown=fixture.PurchaseFlowTests.tearDown
    request=fixture.PurchaseFlowTests.request
    claim=fixture.PurchaseFlowTests.claim
    run_claim=fixture.PurchaseFlowTests.run_claim
    def snapshot(self,claim):
        data=fixture.PurchaseFlowTests.snapshot(self,claim)
        self.rawdoc=fixture.document(str(self.source_product),str(self.source_unit))
        self.staff=copy.deepcopy(fixture.SUPPLIERS);self.staff['supplier']['is_employee']=True
        if getattr(self,'container',False):self.rawdoc['items'][0]['containerId']=str(uuid4())
        data['result']=evaluate([self.rawdoc],self.staff,claim.payload['mapping'],date_from='2026-04-01',date_to='2026-10-21')
        data['analytics']=dict(average=average([self.rawdoc],self.staff,claim.payload['mapping'],start=date(2026,4,1),end=date(2026,11,1),units={}))
        return data
    def prepare(self):
        self.request();self.snapshot_id=self.run_claim(self.claim())['snapshot_id'];self.decision_url=self.path+'/metrics/'+self.snapshot_id+'/admissions'
    def command(self,**changes):
        value=dict(request_id=str(uuid4()),expected_version=self.client.get(self.path).json()['version'],expected_revision=0,kind='EMPLOYEE_PURCHASE',action='GRANT',document_id=self.rawdoc['id'],document_hash=self.rawdoc['source_hash'],line_num='',evidence='Первичный чек №42',comment='Внешняя закупка подтверждена по первичке',primary_checked=True)
        value.update(changes);return value
    def post(self,**changes):return self.client.post(self.decision_url,json=self.command(**changes))
    def recalculate(self):
        self.request();claim=self.claim();data=fixture.PurchaseFlowTests.snapshot(self,claim)
        data['result']=evaluate([self.rawdoc],self.staff,claim.payload['mapping'],date_from='2026-04-01',date_to='2026-10-21')
        data['analytics']=dict(average=average([self.rawdoc],self.staff,claim.payload['mapping'],start=date(2026,4,1),end=date(2026,11,1),units={}))
        return self.run_claim(claim,data)
    def test_grant_idempotency_revoke_replay_and_immutable_snapshots(self):
        self.prepare();before=self.client.get(self.path+'/metrics').json();self.assertEqual(before['current']['status'],'BLOCKED')
        command=self.command();result=self.client.post(self.decision_url,json=command);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.post(self.decision_url,json=command).json()['id'],result.json()['id'])
        self.assertEqual(self.client.post(self.decision_url,json=dict(command,comment='Другое основание')).status_code,409)
        self.assertEqual(self.post(expected_revision=1).status_code,409)
        self.assertEqual(self.client.get(self.path+'/metrics').json()['current']['status'],'BLOCKED') # no rewriting on grant
        calculated=self.recalculate();self.assertEqual(calculated['quality'],'READY')
        for field in ('last_purchase_price','six_month_average'):
            listed=self.client.get('/raw-materials?sort='+field+'&direction=desc').json()['items']
            self.assertEqual(next(r for r in listed if r['id']==str(self.product))[field]['status'],'READY')
        with self.sessions() as db:
            saved=db.get(Snapshot,UUID(calculated['snapshot_id']));payload=copy.deepcopy(saved.payload);content_hash=saved.content_hash
        response=self.post(action='REVOKE',expected_revision=1,primary_checked=False);self.assertEqual(response.status_code,200,response.text)
        current=self.client.get(self.path).json();self.assertEqual(current['last_purchase_price']['status'],'BLOCKED');self.assertIsNone(current['six_month_average']['amount'])
        # Price sorting must use the revoked-safe projection, not the stored historical amount.
        for field in ('last_purchase_price','six_month_average'):
            listed=self.client.get('/raw-materials?sort='+field+'&direction=asc').json()['items']
            metric=next(r for r in listed if r['id']==str(self.product))[field]
            self.assertEqual(metric['status'],'BLOCKED');self.assertIsNone(metric['amount'])
        history=self.client.get(self.path+'/metrics').json();self.assertEqual(history['items'][0]['status'],'READY');self.assertFalse(history['items'][0]['admission_validity']['latest']);self.assertEqual(history['current']['status'],'BLOCKED')
        with self.sessions() as db:
            saved=db.get(Snapshot,UUID(calculated['snapshot_id']));self.assertEqual(saved.payload,payload);self.assertEqual(saved.content_hash,content_hash)
            self.assertEqual(db.scalar(select(func.count()).select_from(Decision).where(Decision.tenant_id==self.tenant)),2)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_type=='MaterialDocumentAdmission',AuditEvent.tenant_id==self.tenant)),2)
        self.assertEqual(self.recalculate()['quality'],'BLOCKED')
        self.assertEqual(self.post(expected_revision=2).status_code,200)
        self.assertEqual(self.recalculate()['quality'],'READY')
    def test_rbac_no_money_leaks_and_tenant_snapshot_scope(self):
        self.prepare();command=self.command();money={'ADMIN','SUPPLY_MANAGER','DIRECTOR','DEPUTY_DIRECTOR','ACCOUNTANT'}
        for role in EmployeeRole:
            self.role(role.value);r=self.client.get(self.path+'/document-admissions');self.assertEqual(r.status_code,200 if role.value in money else 403,role)
            r=self.client.post(self.decision_url,json=dict(command,request_id=str(uuid4())))
            self.assertEqual(r.status_code,200 if role.value=='ADMIN' else 409 if role.value=='SUPPLY_MANAGER' else 403,(role,r.text))
        self.role('ADMIN')
        self.assertEqual(self.client.get('/raw-materials/'+str(self.foreign)+'/document-admissions').status_code,404)
        self.assertEqual(self.client.post(self.path+'/metrics/'+str(uuid4())+'/admissions',json=self.command()).status_code,404)
        self.assertEqual(self.client.post('/raw-materials/'+str(self.second)+'/metrics/'+self.snapshot_id+'/admissions',json=self.command()).status_code,404)
    def test_required_primary_proof_hash_line_and_optimistic_version(self):
        self.prepare()
        for changes,status in [(dict(primary_checked=False),422),(dict(evidence=''),422),(dict(comment=''),422),(dict(document_hash='0'*64),409),(dict(line_num='2'),409),(dict(expected_version=999),409),(dict(action='REVOKE'),409)]:
            r=self.post(**changes);self.assertEqual(r.status_code,status,(changes,r.text))
        r=self.post(line_num='1');self.assertEqual(r.status_code,200,r.text)
    def test_container_validation_is_separate_from_employee_grant(self):
        self.container=True;self.prepare();self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.recalculate()['quality'],'BLOCKED')
        base=dict(kind='BASE_UNIT_CONTAINER',line_num='1',verified_unit_id=str(self.source_unit),verified_quantity='3')
        for changes in (dict(line_num=''),dict(verified_quantity='6'),dict(verified_unit_id=str(uuid4()))):
            self.assertIn(self.post(**{**base,**changes}).status_code,(409,422))
        r=self.post(**base);self.assertEqual(r.status_code,200,r.text);self.assertEqual(self.recalculate()['quality'],'READY')
        self.assertEqual(self.post(**base).status_code,409)
    def test_audit_failure_rolls_back_and_inflight_scope_change_rejected(self):
        self.prepare();before=self.client.get(self.path).json()['version']
        with patch.object(admissions,'record_audit_event',side_effect=RuntimeError('fixture audit failure')):
            with self.assertRaises(RuntimeError):self.post()
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Decision).where(Decision.tenant_id==self.tenant)),0)
        self.assertEqual(self.client.get(self.path).json()['version'],before)
        self.request();claim=self.claim();data=fixture.PurchaseFlowTests.snapshot(self,claim)
        self.assertEqual(self.post().status_code,200)
        with self.assertRaisesRegex(ValueError,'SCOPE_CHANGED'):self.run_claim(claim,data)
