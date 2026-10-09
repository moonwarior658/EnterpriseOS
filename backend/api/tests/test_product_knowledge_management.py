"""K2 backend access matrix, preserved identities/local data, audit and UUID confirmations."""
import unittest
from unittest.mock import patch, AsyncMock
from uuid import UUID, uuid4
from sqlalchemy import select, func
from app.models.employee import EmployeeRole, EmployeeRoleAssignment
from app.models.supply import Department, SupplyProductCategory
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgeBatch as Batch
from app.models.audit import AuditEvent
from tests import test_product_knowledge as k1


class ProductKnowledgeManagementTests(unittest.TestCase):
    row = k1.ProductKnowledgeTests.row
    ingest = k1.ProductKnowledgeTests.ingest
    plan = k1.ProductKnowledgeTests.plan
    load = k1.ProductKnowledgeTests.load
    tearDown = k1.ProductKnowledgeTests.tearDown
    def setUp(self):
        k1.ProductKnowledgeTests.setUp(self)
        self.load()
        self.first = self.client.get('/products').json()['items'][0]
        self.pid = self.first['id']

    def command(self, **extra):
        return dict(expected_version=self.client.get('/products/'+self.pid).json()['version'], reason='Проверка K2', **extra)

    def test_exact_access_matrix_all_routes(self):
        for role in EmployeeRole:
            with self.sessions.begin() as db:
                for assignment in db.scalars(select(EmployeeRoleAssignment)): assignment.role = role
                db.get(Department,self.department_id).business_type='PRODUCTION'
            readable = role in {EmployeeRole.ADMIN, EmployeeRole.NETWORK_MANAGER, EmployeeRole.DIRECTOR,
                EmployeeRole.DEPUTY_DIRECTOR, EmployeeRole.CHEF_CONFECTIONER, EmployeeRole.HEAD_OF_PRODUCTION}
            writable = readable and role not in {EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR}
            result=self.client.get('/products')
            self.assertEqual(result.status_code,200 if readable else 403,role)
            self.assertEqual(self.client.get('/products/'+self.pid+'/history').status_code,200 if readable else 403,role)
            if readable:self.assertEqual('ADD' in result.json()['allowed_actions'],writable)
            with self.sessions() as db:version=db.get(Product,UUID(self.pid)).version
            base=dict(expected_version=version,reason='Матрица прав')
            self.assertEqual(self.client.patch('/products/'+self.pid+'/verification',json={**base,'verified':True}).status_code,200 if writable else 403,role)
            if not writable:
                for method,path,body in [('PATCH','/knowledge',{**base,'name':'Запрещено'}),('PATCH','/sale-status',{**base,'sale_status':'OFF_SALE'}),('DELETE','',base),('POST','/restore',base)]:
                    self.assertEqual(self.client.request(method,'/products/'+self.pid+path,json=body).status_code,403,role)
                with patch('app.api.routes.product_knowledge.collect',side_effect=AssertionError('Forbidden network')):
                    self.assertEqual(self.client.get('/products/iiko-candidates?q=x').status_code,403,role)
                    self.assertEqual(self.client.post('/products',json={'source_id':self.source_id,'iiko_product_id':str(uuid4()),'confirmation_hash':'a'*64,'sale_status':'OFF_SALE','reason':'forbidden'}).status_code,403,role)

    def test_edit_verify_filter_progress_and_preservation(self):
        with self.sessions.begin() as db:
            category=SupplyProductCategory(tenant_id='eclair',code='CAKES',name='Торты',normalized_name='торты')
            db.add(category);db.flush();cid=str(category.id)
        edit=self.command(name='Название EOS',category_id=cid,description='Описание EOS',characteristics='Форма',composition='Мука',allergens='Глютен',storage='Холодильник',training='Материалы')
        result=self.client.patch('/products/'+self.pid+'/knowledge',json=edit)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['category_name'],'Торты')
        result=self.client.patch('/products/'+self.pid+'/verification',json=self.command(verified=True))
        self.assertEqual(result.status_code,200,result.text);self.assertTrue(result.json()['verified_by_employee_id'])
        self.assertEqual(self.client.get('/products?unverified=true').json()['total'],1)
        self.assertEqual(self.client.get('/products?q=Название').json()['verified_count'],1)
        self.assertEqual(self.client.get('/products?q=НетТакого').json()['active_count'],2)
        with self.sessions.begin() as db:
            p=db.get(Product,UUID(self.pid));p.name='Имя источника';p.description='Описание источника';p.source_deleted=True
        self.load()
        result=self.client.get('/products/'+self.pid).json()
        self.assertEqual(result['name'],'Название EOS');self.assertEqual(result['description'],'Описание EOS');self.assertEqual(result['description_source'],'EOS');self.assertTrue(result['verified_at'])
        result=self.client.patch('/products/'+self.pid+'/knowledge',json=self.command(name='Новое название'))
        self.assertEqual(result.status_code,200);self.assertIsNone(result.json()['verified_at'])
        for extra in ({'iiko_product_id':str(uuid4())},{'source_id':'x'},{'published':False},{'unit_id':str(uuid4())},{'verified_by_name':'fake'}):
            self.assertEqual(self.client.patch('/products/'+self.pid+'/knowledge',json={**self.command(name='EOS'),**extra}).status_code,422)
        self.assertEqual(self.client.patch('/products/'+self.pid+'/knowledge',json=self.command(name='  ')).status_code,422)
        self.assertEqual(self.client.patch('/products/'+self.pid+'/knowledge',json=self.command(name='EOS',category_id=str(uuid4()))).status_code,422)
        with self.sessions() as db:
            events=list(db.scalars(select(AuditEvent).where(AuditEvent.entity_id==self.pid)))
            self.assertEqual([e.operation for e in events],['EDIT','VERIFY','EDIT'])
            self.assertTrue(all(e.actor_employee_id and e.authorized_as=='ADMIN' for e in events))

    def test_status_delete_restore_conflict_retry_and_history(self):
        command=self.command(sale_status='OFF_SALE')
        result=self.client.patch('/products/'+self.pid+'/sale-status',json=command)
        self.assertEqual(result.status_code,200);self.assertFalse(result.json()['eligible_for_production'])
        self.assertEqual(self.client.patch('/products/'+self.pid+'/sale-status',json=command).status_code,200)
        self.assertEqual(self.client.patch('/products/'+self.pid+'/sale-status',json={**command,'sale_status':'ON_SALE'}).status_code,409)
        deleted=self.command()
        for _ in range(2):self.assertEqual(self.client.request('DELETE','/products/'+self.pid,json=deleted).status_code,200)
        self.assertEqual(self.client.get('/products').json()['total'],1)
        self.assertEqual(self.client.get('/products?deleted=true').json()['total'],1)
        self.assertEqual(self.client.get('/products/'+self.pid).json()['allowed_actions'],['RESTORE'])
        self.assertEqual(self.client.patch('/products/'+self.pid+'/verification',json=self.command(verified=True)).status_code,409)
        result=self.client.post('/products/'+self.pid+'/restore',json=self.command())
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['sale_status'],'OFF_SALE')
        self.assertEqual(self.client.get('/products').json()['total'],2)
        history=self.client.get('/products/'+self.pid+'/history').json()
        self.assertEqual({e['operation'] for e in history},{'STATUS','DELETE','RESTORE'})
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Product)),2)
            self.assertEqual(db.scalar(select(func.count()).select_from(Batch)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id==self.pid)),3)
        self.assertEqual(self.client.patch('/products/'+str(uuid4())+'/sale-status',json=command).status_code,404)

    def test_manual_uuid_add_stale_selection_readd_and_k1_batch(self):
        snapshot=self.snapshot.model_copy(deep=True);new=snapshot.products[0].model_copy(update={'id':uuid4()});snapshot.products.append(new)
        with patch('app.api.routes.product_knowledge.collect',new=AsyncMock(return_value=snapshot)):
            rows=self.client.get('/products/iiko-candidates?q='+str(new.id)).json();self.assertEqual(len(rows),1)
            body={**{k:rows[0][k] for k in ('source_id','iiko_product_id','confirmation_hash')},'sale_status':'OFF_SALE','reason':'Подтверждён UUID'}
            self.assertEqual(self.client.post('/products',json={**body,'confirmation_hash':'0'*64}).status_code,409)
            result=self.client.post('/products',json=body);self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(self.client.post('/products',json=body).json()['id'],result.json()['id'])
            self.assertEqual(self.client.get('/products').json()['total'],3)
            self.assertEqual(self.client.get('/products/iiko-candidates?q='+str(new.id)).json(),[])
            self.client.request('DELETE','/products/'+self.pid,json=self.command())
            with self.sessions() as db:external=db.get(Product,UUID(self.pid)).iiko_product_id
            row=self.client.get('/products/iiko-candidates?q='+str(external)).json()[0]
            readd={**{k:row[k] for k in ('source_id','iiko_product_id','confirmation_hash')},'sale_status':'ON_SALE','reason':'Повторное добавление UUID'}
            result=self.client.post('/products',json=readd);self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['id'],self.pid);self.assertTrue(result.json()['eligible_for_production'])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Product)),3)
            k1_batch=db.scalar(select(Batch).where(Batch.plan_hash==self.plan()['plan_hash']))
            self.assertEqual(k1_batch.report['ready'],2);self.assertIsNone(k1_batch.rolled_back_at)

    def test_audit_failure_rolls_back(self):
        with patch('app.product_knowledge.management.record_audit_event',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.client.patch('/products/'+self.pid+'/sale-status',json=self.command(sale_status='OFF_SALE'))
        self.assertEqual(self.client.get('/products/'+self.pid).json()['sale_status'],'ON_SALE')

    def test_foreign_tenant_write_and_production_guard(self):
        from app.product_knowledge.management import require_production_eligible
        from fastapi import HTTPException
        with self.sessions() as db:
            with self.assertRaises(HTTPException):require_production_eligible(db,'foreign',UUID(self.pid))
        with self.sessions.begin() as db: db.get(Product,UUID(self.pid)).published=False
        for method,path,body in [('PATCH','/knowledge',{'name':'Не менять'}),('PATCH','/sale-status',{'sale_status':'ON_SALE'}),('DELETE','',{}),('POST','/restore',{})]:
            self.assertEqual(self.client.request(method,'/products/'+self.pid+path,json={'expected_version':1,'reason':'Не менять',**body}).status_code,404)

    def test_manual_conflicting_mapping_and_changed_source_fail_closed(self):
        from app.models.iiko import IikoProductMapping
        snapshot=self.snapshot.model_copy(deep=True);new=snapshot.products[0].model_copy(update={'id':uuid4()});snapshot.products.append(new)
        with patch('app.api.routes.product_knowledge.collect',new=AsyncMock(return_value=snapshot)):
            row=self.client.get('/products/iiko-candidates?q='+str(new.id)).json()[0]
            body={**{k:row[k] for k in ('source_id','iiko_product_id','confirmation_hash')},'sale_status':'ON_SALE','reason':'UUID test'}
            new.name='Данные изменились'
            self.assertEqual(self.client.post('/products',json=body).status_code,409)
            row=self.client.get('/products/iiko-candidates?q='+str(new.id)).json()[0];body['confirmation_hash']=row['confirmation_hash']
            with self.sessions.begin() as db:db.add(IikoProductMapping(tenant_id='eclair',iiko_product_id=new.id,status='CONFLICT',source_name='Конфликт',is_deleted=False))
            self.assertEqual(self.client.post('/products',json=body).status_code,409)
            self.assertEqual(self.client.get('/products').json()['total'],2)

    def test_foreign_product_mutation_history_and_source_error_are_safe(self):
        from app.integrations.iiko.exceptions import IikoConnectionError
        k1.ProductKnowledgeTests.test_foreign_tenant_product_not_found(self)
        with self.sessions() as db: foreign=str(db.scalar(select(Product.id).where(Product.tenant_id=='other')))
        for method,path,body in [('PATCH','/knowledge',{'name':'Запрещено'}),('PATCH','/sale-status',{'sale_status':'ON_SALE'}),('DELETE','',{}),('POST','/restore',{}),('PATCH','/verification',{'verified':True})]:
            self.assertEqual(self.client.request(method,'/products/'+foreign+path,json={'expected_version':1,'reason':'Tenant guard',**body}).status_code,404)
        self.assertEqual(self.client.get('/products/'+foreign+'/history').status_code,404)
        with patch('app.api.routes.product_knowledge.collect',new=AsyncMock(side_effect=IikoConnectionError('sensitive fixture details'))):
            response=self.client.get('/products/iiko-candidates?q=x')
            self.assertEqual(response.status_code,503);self.assertNotIn('sensitive',response.text)
