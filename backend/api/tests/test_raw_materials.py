"""R-M1 API, RBAC, isolation, immutable knowledge, private photos, no metric fallback."""
import os
os.environ.setdefault('POSTGRES_DB','test')
os.environ.setdefault('POSTGRES_USER','test')
os.environ.setdefault('POSTGRES_PASSWORD','test')
os.environ.setdefault('JWT_SECRET_KEY','test-jwt-secret')
import json
import tempfile
import unittest
from io import BytesIO
from uuid import uuid4
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func, update
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.api.routes.raw_materials import router
from app.models.user import User
from app.models.employee import EmployeeRole, EmployeeRoleAssignment
from app.models.raw_material import RawMaterialProfile as Profile, MaterialSpecificationVersion as Specification, MaterialSpecificationApproval as Approval
from app.models.supply import Department, SupplyUnit, SupplyProduct, SupplyProductCategory, SupplyStorageZone, SupplyRequestDirection, SupplySupplier, SupplyProductSupplier, SupplyProductAlias
from app.models.iiko import IikoUnitMapping
from app.models.audit import AuditEvent
from app.raw_materials import service
from tests import test_employee_iiko_identity as fixture


class RawMaterialTests(unittest.TestCase):
    def setUp(self):
        fixture.EmployeeIikoIdentityTests.setUp(self)
        for model in (SupplyUnit, SupplyProductCategory, SupplyStorageZone, SupplyRequestDirection, SupplyProduct, SupplySupplier, SupplyProductSupplier, SupplyProductAlias, IikoUnitMapping, Profile, Specification, Approval):
            model.__table__.create(self.engine)
        self.seed()
        self.bind_client()

    def seed(self):
        self.tenant=getattr(self,'tenant','eclair'); self.actor_id=getattr(self,'actor_id',1)
        self.product,self.second,self.foreign,self.unit,self.supplier,self.backup=[uuid4() for _ in range(6)]
        with self.sessions.begin() as db:
            db.get(Department,self.department_id).business_type='PRODUCTION'
            unit=SupplyUnit(id=self.unit,tenant_id=self.tenant,code='KG',name_ru='Килограмм',short_name_ru='кг',allows_fraction=True)
            db.add(unit);db.flush()
            for pid,name,tenant in [(self.product,'Сливки',self.tenant),(self.second,'Мука',self.tenant),(self.foreign,'Чужое сырьё',self.tenant+'-foreign')]:
                db.add(SupplyProduct(id=pid,tenant_id=tenant,name=name,normalized_name=name.lower(),default_unit_id=self.unit,iiko_id=str(uuid4())))
            db.add_all([SupplySupplier(id=self.supplier,tenant_id=self.tenant,display_name='Основной поставщик'),SupplySupplier(id=self.backup,tenant_id=self.tenant,display_name='Резервный поставщик')]);db.flush()
            db.add(SupplyProductAlias(tenant_id=self.tenant,product_id=self.product,alias='cream',normalized_alias='cream',status='APPROVED'))
            db.add(IikoUnitMapping(tenant_id=self.tenant,iiko_unit_id=uuid4(),eos_unit_id=self.unit,status='CONFIRMED',source_name='кг',is_deleted=False))
            db.add_all([SupplyProductSupplier(tenant_id=self.tenant,product_id=self.product,supplier_id=sid,role=role,priority=n,package_quantity=1,package_unit_id=self.unit,price_per_package='98765.43',currency='RUB',is_available=True) for n,(sid,role) in enumerate([(self.supplier,'PRIMARY'),(self.backup,'BACKUP')])])

    def bind_client(self):
        self.temp=tempfile.TemporaryDirectory(prefix='eos-rm1-photos-')
        self.photo_patch=patch('app.core.config.settings.raw_material_photo_upload_dir',self.temp.name);self.photo_patch.start()
        app=FastAPI();app.include_router(router)
        def dependency():
            with self.sessions() as db:yield db
        def actor():
            with self.sessions() as db:return db.get(User,self.actor_id)
        app.dependency_overrides[get_db]=dependency;app.dependency_overrides[get_current_user]=actor
        self.client=TestClient(app)

    def tearDown(self):
        self.client.close();self.photo_patch.stop();self.temp.cleanup();self.engine.dispose()

    def role(self,role):
        with self.sessions.begin() as db:
            db.get(User,self.actor_id).is_admin=False
            for assignment in db.scalars(select(EmployeeRoleAssignment).where(EmployeeRoleAssignment.tenant_id==self.tenant, EmployeeRoleAssignment.employee_id==self.admin_employee_id)):assignment.role=role

    def enroll(self,product=None,kind='RAW_MATERIAL'):
        response=self.client.post('/raw-materials',json=dict(product_id=str(product or self.product),kind=kind,reason='Состав подтверждён владельцем в тестовом окружении'))
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def save(self,data=None,version=None):
        current=self.client.get('/raw-materials/'+str(self.product)).json()
        return self.client.patch('/raw-materials/'+str(self.product)+'/knowledge',json=dict(expected_version=version or current['version'],reason='Консультация с кондитерами',knowledge=data or dict(purpose='Для крема',manufacturer='БМК',characteristics='33 %',unit_weight_kg='0.95',weight_evidence='Проверка нетто упаковки')))

    def confirm(self,body=None):
        current=body or self.client.get('/raw-materials/'+str(self.product)).json()
        return self.client.post('/raw-materials/'+str(self.product)+'/knowledge/confirm',json=dict(expected_version=current['version'],reason='Версия проверена после консультаций',specification_id=current['latest']['id'],content_hash=current['latest']['content_hash'],primary_product_id=str(self.product)))

    def test_empty_registry_enroll_explicit_no_seed_or_supply_mutation(self):
        self.assertEqual(self.client.get('/raw-materials').json()['total'],0)
        self.assertEqual(self.client.get('/raw-materials/candidates').json()['total'],2)
        first=self.enroll();self.enroll()
        self.assertEqual(first['id'],str(self.product));self.assertIsNone(first['last_purchase_price']['amount'])
        self.assertNotIn('98765',json.dumps(first));self.assertEqual(first['unit'],'кг')
        self.assertEqual(first['primary_supplier']['name'],'Основной поставщик')
        self.assertEqual(first['backup_supplier']['name'],'Резервный поставщик')
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SupplyProduct)),3)
            self.assertEqual(db.get(SupplyProduct,self.product).name,'Сливки')
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_type==service.ENTITY)),1)
        self.assertEqual(self.client.post('/raw-materials',json=dict(product_id=str(self.foreign),kind='RAW_MATERIAL',reason='Нельзя включать')).status_code,404)
        self.assertEqual(self.client.get('/raw-materials/'+str(self.foreign)).status_code,404)

    def test_search_filters_pagination_literal_wildcards_and_archive(self):
        self.enroll();self.enroll(self.second,'PACKAGING')
        for query in ('q=cream','q='+str(self.product),'kind=PACKAGING','supplier_id='+str(self.supplier),'without_supplier=true','q=слив'):
            result=self.client.get('/raw-materials?'+query).json();self.assertEqual(result['total'],1,query)
        self.assertEqual(self.client.get('/raw-materials?q=%25').json()['total'],0)
        self.assertEqual(self.client.get('/raw-materials?limit=1').json()['items'][0]['id'],str(self.second))
        self.assertEqual(self.client.get('/raw-materials?limit=1&offset=1').json()['items'][0]['id'],str(self.product))
        self.assertEqual(self.client.get('/raw-materials?sort=last_purchase_price').status_code,422)
        self.assertEqual(self.client.get('/raw-materials?limit=101').status_code,422)
        r=self.client.patch('/raw-materials/'+str(self.product)+'/archive',json=dict(expected_version=1,reason='Тест архива',archived=True));self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/raw-materials?archived=true').json()['total'],1)
        self.assertEqual(self.save().status_code,409)
        with self.sessions() as db:self.assertTrue(db.get(SupplyProduct,self.product).is_active)

    def test_versions_confirmation_conflict_history_and_no_money_inputs(self):
        self.role('SUPPLY_MANAGER');self.enroll()
        saved=self.save();self.assertEqual(saved.status_code,200,saved.text)
        self.assertIsNone(saved.json()['current']);self.assertIsNone(saved.json()['unit_weight_kg'])
        self.assertEqual(self.save(version=1).status_code,409)
        self.assertEqual(self.confirm(saved.json()).status_code,200)
        self.assertEqual(self.confirm(saved.json()).status_code,409)
        current=self.client.get('/raw-materials/'+str(self.product)).json()
        self.assertEqual(current['unit_weight_kg'],'0.95');self.assertEqual(current['current']['knowledge']['manufacturer'],'БМК')
        self.save(dict(purpose='Новый черновик'))
        current=self.client.get('/raw-materials/'+str(self.product)).json()
        self.assertEqual(current['current']['revision'],1);self.assertEqual(current['latest']['revision'],2)
        self.assertEqual(self.confirm(saved.json()).status_code,409)
        history=self.client.get('/raw-materials/'+str(self.product)+'/history?limit=1').json()
        self.assertEqual(history['total'],2);self.assertEqual(len(history['versions']),1)
        self.assertEqual(history['event_total'],4)
        self.assertEqual(self.save(dict(last_purchase_price='98765')).status_code,422)
        self.assertEqual(self.save(dict(unit_weight_kg='1',weight_evidence='')).status_code,422)
        self.assertEqual(self.client.get('/raw-materials?state=CONFIRMED').json()['total'],1)
        with self.sessions() as db:
            event=db.scalar(select(AuditEvent).where(AuditEvent.operation=='CONFIRMED'))
            self.assertEqual(event.authorized_as,'SUPPLY_MANAGER');self.assertEqual(event.actor_user_id,1)

    def test_every_role_money_redaction_read_write_tenant_and_sort(self):
        self.enroll();self.save();self.confirm()
        confirmed=self.client.get('/raw-materials/'+str(self.product)).json()
        money={'ADMIN','SUPPLY_MANAGER','DIRECTOR','DEPUTY_DIRECTOR','ACCOUNTANT'}
        readers=money|{'HEAD_OF_PRODUCTION','CHEF_CONFECTIONER','CONFECTIONER','BAKER'}
        for role in EmployeeRole:
            with self.subTest(role=role):
                self.role(role)
                response=self.client.get('/raw-materials');self.assertEqual(response.status_code,200 if role in readers else 403,response.text)
                for path in ['/'+str(self.product),'/'+str(self.product)+'/history']:
                    response=self.client.get('/raw-materials'+path)
                    self.assertEqual(response.status_code,200 if role in readers else 403)
                    self.assertNotIn('98765',response.text)
                if role in readers:
                    result=self.client.get('/raw-materials/'+str(self.product)).json()
                    self.assertEqual('last_purchase_price' in result,role in money)
                    self.assertEqual('six_month_average' in result,role in money)
                    self.assertEqual(result['purchase_access'],role in money)
                    self.assertEqual(self.client.get('/raw-materials?sort=six_month_average').status_code,422)
                    self.assertEqual(self.client.get('/raw-materials/'+str(self.foreign)).status_code,404)
                if role not in {'ADMIN','SUPPLY_MANAGER'}:
                    self.assertEqual(self.save(version=1).status_code,403)
                    self.assertEqual(self.client.get('/raw-materials/candidates').status_code,403)
                    self.assertEqual(self.client.post('/raw-materials',json=dict(product_id=str(self.second),kind='RAW_MATERIAL',reason='Forbidden fixture')).status_code,403)
                    self.assertEqual(self.confirm(confirmed).status_code,403)
                    self.assertEqual(self.client.patch('/raw-materials/'+str(self.product)+'/archive',json=dict(expected_version=confirmed['version'],reason='Forbidden fixture',archived=True)).status_code,403)
                    self.assertEqual(self.client.put('/raw-materials/'+str(self.product)+'/photo',data=dict(expected_version=confirmed['version'],reason='Forbidden fixture'),files={'file':('bad.png',b'bad','image/png')}).status_code,403)
        self.role('HEAD_OF_PRODUCTION')
        # A historical/future monetary field must not be exposed by generic payload serialization.
        with self.sessions.begin() as db:
            row=db.scalar(select(Specification));row.payload={**row.payload,'last_purchase_price':'98765.43'}
            event=db.scalar(select(AuditEvent).where(AuditEvent.entity_type==service.ENTITY));db.execute(update(AuditEvent).where(AuditEvent.id==event.id).values(after={**event.after,'price':'98765.43'}))
        # SQLite does not emulate PG immutable triggers; the hostile storage case tests projection only.
        for path in ['', '/'+str(self.product), '/'+str(self.product)+'/history']:
            response=self.client.get('/raw-materials'+path);self.assertNotIn('98765',response.text)

    def test_safe_private_photo_historical_binding_and_rollback(self):
        self.enroll();image=BytesIO();Image.new('RGB',(16,20),'red').save(image,format='PNG')
        route='/raw-materials/'+str(self.product)+'/photo'
        response=self.client.put(route,data=dict(expected_version=1,reason='Фото упаковки'),files={'file':('test.png',image.getvalue(),'image/png')})
        self.assertEqual(response.status_code,200,response.text);photo_hash=response.json()['photo_hash']
        photo=self.client.get(route);self.assertEqual(photo.status_code,200);self.assertEqual(photo.headers['cache-control'],'no-store');self.assertEqual(photo.headers['content-type'],'image/webp')
        self.assertEqual(self.client.get('/raw-materials/'+str(self.foreign)+'/photo?photo_hash='+photo_hash).status_code,404)
        self.assertEqual(self.client.get(route+'?photo_hash='+'a'*64).status_code,404)
        for content,mime,expected in [(b'<svg>','image/svg+xml',415),(b'bad','image/png',422),(b'x'*(10*1024*1024+1),'image/png',413)]:
            response=self.client.put(route,data=dict(expected_version=2,reason='Некорректное фото'),files={'file':('bad',content,mime)})
            self.assertEqual(response.status_code,expected,response.text)
        self.assertEqual(self.client.request('DELETE',route,json=dict(expected_version=2,reason='Убрать фото')).status_code,200)
        self.assertEqual(self.client.get(route).status_code,404)
        self.assertEqual(self.client.get(route+'?photo_hash='+photo_hash).status_code,200)
        self.role('SELLER');self.assertEqual(self.client.get(route+'?photo_hash='+photo_hash).status_code,403)
        self.assertEqual(len(list(Path(self.temp.name).rglob('*.webp'))),1)
