"""K1 publication, identity, authorization and safe DB-only API."""
import copy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from tests import test_sales_foundation as foundation
from app.api.dependencies import get_current_user
from app.api.routes.product_knowledge import router
from app.db.session import get_db
from app.models.employee import EmployeeRole, EmployeeRoleAssignment
from app.models.iiko import IikoProductMapping, IikoUnitMapping
from app.models.sales import SalesSyncState, SalesDaySync
from app.models.supply import SupplyUnit, SupplyProductCategory, SupplyRequestDirection, SupplyStorageZone
from app.models.user import User
from app.models.product_knowledge import ProductKnowledgeBatch, ProductKnowledgeProduct, ProductKnowledgePrice, ProductKnowledgePriceSnapshot
from app.product_knowledge.bootstrap import preview, publish, rollback_publication, PublicationError
from app.schemas.product_knowledge import SourceSnapshot, ConfirmedPrice
from app.models.audit import AuditEvent


class ProductKnowledgeTests(unittest.TestCase):
    row = foundation.SalesFoundationTests.row
    ingest = foundation.SalesFoundationTests.ingest

    def setUp(self):
        foundation.SalesFoundationTests.setUp(self)
        for model in (SupplyUnit, SupplyProductCategory, SupplyRequestDirection, SupplyStorageZone, IikoUnitMapping,
                      ProductKnowledgeBatch, ProductKnowledgeProduct, ProductKnowledgePrice, ProductKnowledgePriceSnapshot):
            model.__table__.create(self.engine)
        from sqlalchemy import MetaData, JSON, Integer, BigInteger
        from sqlalchemy.dialects.postgresql import JSONB
        from app.models.automation import AutomationSchedule, AutomationExecution
        metadata = MetaData()
        User.__table__.to_metadata(metadata)
        for model in (AutomationSchedule, AutomationExecution):
            table = model.__table__.to_metadata(metadata)
            for column in table.columns:
                if isinstance(column.type, JSONB):
                    column.type = JSON(); column.server_default = None
                if column.primary_key and isinstance(column.type, BigInteger):
                    column.type = Integer()
            table.create(self.engine, checkfirst=True)
        self.unit, self.second = uuid4(), uuid4()
        self.snapshot = SourceSnapshot(source_id=self.source_id, observed_at=datetime(2026,10,8,tzinfo=timezone.utc),
            evidence='confirmed source read', complete=True,
            products=[dict(id=p,name='Эклер',main_unit=self.unit,unit_weight_kg='0.05000000001',deleted=False,source_type='DISH') for p in [self.product,self.second]],
            units=[dict(id=self.unit,name='шт')])
        with self.sessions.begin() as db:
            db.get(SalesSyncState, ('eclair',self.source_id)).history_from=date(2026,9,1)
            for day in range(30):
                db.add(SalesDaySync(tenant_id='eclair',source_id=self.source_id,business_date=date(2026,9,1)+timedelta(days=day),
                    last_success_at=foundation.NOW,row_count=0))
        rows=[self.row(**{'DishId':str(p),'OpenDate.Typed':'2026-09-15','OpenTime':'2026-09-15T10:00:00','CloseTime':'2026-09-15T10:01:00'}) for p in [self.product,self.second]]
        self.ingest(rows,day=date(2026,9,15))
        app=FastAPI(); app.include_router(router)
        def dependency():
            with self.sessions() as db: yield db
        def actor():
            with self.sessions() as db: return db.get(User,1)
        app.dependency_overrides[get_db]=dependency;app.dependency_overrides[get_current_user]=actor
        self.client=TestClient(app)

    def tearDown(self):
        self.client.close();self.engine.dispose()

    def plan(self, snapshot=None):
        with self.sessions() as db: return preview(db,'eclair',self.source_id,snapshot or self.snapshot)

    def load(self, plan=None):
        plan=plan or self.plan()
        with self.sessions.begin() as db:
            return publish(db,db.get(User,1),plan,expected_hash=plan['plan_hash'],initial_status='ON_SALE',confirmed_point_ids=[self.department_id]).id

    def test_uuid_identity_same_names_retry_and_no_expansion(self):
        plan=self.plan(); self.assertEqual((plan['found'],plan['ready'],plan['conflicts']),(2,2,0))
        self.assertTrue(plan['complete']); self.assertEqual(plan['sale_modes_confirmed'],0)
        batch=self.load(plan);self.assertEqual(self.load(plan),batch)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(ProductKnowledgeProduct)),2)
            self.assertEqual(db.scalar(select(func.count()).select_from(ProductKnowledgeBatch)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type=='PRODUCT_KNOWLEDGE_PUBLISHED')),1)
        different=self.snapshot.model_copy(deep=True);different.products[0].name='Новое название'
        with self.assertRaisesRegex(PublicationError,'BOOTSTRAP_ALREADY_EXISTS'): self.load(self.plan(different))

    def test_incomplete_september_blocks_all_and_keeps_candidates(self):
        with self.sessions.begin() as db: db.delete(db.get(SalesDaySync,('eclair',self.source_id,date(2026,9,1))))
        plan=self.plan();self.assertEqual(plan['found'],2);self.assertFalse(plan['complete'])
        with self.assertRaisesRegex(PublicationError,'INCOMPLETE'):self.load(plan)

    def test_uuid_and_unit_conflicts_preserved_in_report(self):
        snapshot=self.snapshot.model_copy(deep=True);snapshot.products.append(snapshot.products[0])
        plan=self.plan(snapshot);self.assertEqual((plan['ready'],plan['conflicts']),(1,1));self.assertEqual(len(plan['rows']),2)
        snapshot=self.snapshot.model_copy(deep=True);snapshot.units=[]
        self.assertEqual(self.plan(snapshot)['ready'],0)
        with self.sessions.begin() as db:
            db.add(IikoProductMapping(tenant_id='eclair',iiko_product_id=self.product,status='CONFLICT',source_name='Эклер',is_deleted=False))
        self.assertEqual(self.plan()['conflicts'],1)

    def test_rollback_hides_without_deletion_and_is_idempotent(self):
        batch=self.load()
        with self.sessions.begin() as db: rollback_publication(db,db.get(User,1),batch)
        with self.sessions.begin() as db: rollback_publication(db,db.get(User,1),batch)
        self.assertEqual(self.client.get('/products').json()['total'],0)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(ProductKnowledgeProduct)),2)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type=='PRODUCT_KNOWLEDGE_UNPUBLISHED')),1)
        with self.assertRaisesRegex(PublicationError,'ROLLED_BACK'):self.load()

    def test_api_search_pagination_and_safe_detail(self):
        self.load()
        with patch('app.integrations.iiko.client.IikoServerClient.authenticate',side_effect=AssertionError('No network')):
            result=self.client.get('/products?q=Эклер&limit=1').json()
            self.assertEqual((result['total'],len(result['items'])),(2,1));first=result['items'][0]
            second=self.client.get('/products?offset=1&limit=1').json()['items'][0]
            self.assertNotEqual(first['id'],second['id'])
            self.assertEqual(self.client.get('/products?q=%').json()['total'],0)
            self.assertEqual(self.client.get('/products?mode=PORTION').json()['total'],0)
            self.assertEqual(self.client.get('/products?mode=UNKNOWN').json()['total'],2)
            self.assertEqual(self.client.get('/products?status=OFF_SALE').json()['total'],0)
            detail=self.client.get('/products/'+first['id']).json()
            self.assertIsNone(detail['price']);self.assertIsNone(detail['photo'])
            for key in ('cost','recipe','raw_payload','iiko_product_id','provenance'):self.assertNotIn(key,detail)
            self.assertEqual(detail['allowed_actions'],['EDIT','STATUS','DELETE','VERIFY'])
        self.assertEqual(self.client.get('/products?limit=101').status_code,422)
        self.assertEqual(self.client.get('/products?department_id='+str(uuid4())).status_code,404)
        with self.sessions.begin() as db:
            for p in db.scalars(select(ProductKnowledgeProduct)):p.published=False
        self.assertEqual(self.client.get('/products/'+first['id']).status_code,404)

    def test_confirmed_price_context_and_overlap_rejection(self):
        snapshot=self.snapshot.model_copy(deep=True)
        price=ConfirmedPrice(iiko_product_id=self.product,department_id=self.department_id,
            valid_from=date(2026,10,1),valid_to=date(2026,11,1),amount='140',currency='RUB',price_unit='шт',evidence='Office verified')
        snapshot.prices=[price];self.load(self.plan(snapshot))
        result=self.client.get('/products?department_id='+str(self.department_id)+'&price_at=2026-10-08').json()
        confirmed=[x for x in result['items'] if x['price']]
        self.assertEqual(len(confirmed),1);self.assertEqual(Decimal(confirmed[0]['price']['amount']),140)
        self.assertIsNone(self.client.get('/products/'+confirmed[0]['id']+'?department_id='+str(self.department_id)+'&price_at=2026-11-01').json()['price'])
        snapshot.prices=[price,price.model_copy(update={'valid_from':date(2026,10,2)})]
        self.assertEqual(self.plan(snapshot)['conflicts'],1)

    def test_actor_role_and_review_hash_required(self):
        plan=self.plan()
        with self.sessions.begin() as db:
            with self.assertRaisesRegex(PublicationError,'PLAN_REVIEW'):
                publish(db,db.get(User,1),plan,expected_hash='bad',initial_status='ON_SALE',confirmed_point_ids=[self.department_id])
        with self.sessions.begin() as db:
            for role in db.scalars(select(EmployeeRoleAssignment)):role.role=EmployeeRole.HANDYMAN
        self.assertEqual(self.client.get('/products').status_code,403)

    def test_invalid_manifest_and_tampered_plan(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SourceSnapshot.model_validate({**self.snapshot.model_dump(),'prices':[{'amount':'NaN'}]})
        modified=copy.deepcopy(self.plan());modified['rows'][0]['name']='tampered'
        with self.assertRaisesRegex(PublicationError,'MODIFIED'):self.load(modified)

    def test_source_sale_mode_not_inferred_from_unit(self):
        snapshot=self.snapshot.model_copy(deep=True)
        snapshot.products[0].use_balance_for_sell=True
        snapshot.products[1].use_balance_for_sell=False
        plan=self.plan(snapshot)
        self.assertEqual(plan['sale_modes_confirmed'],2)
        self.assertEqual({x['sale_mode'] for x in plan['rows']},{'WEIGHT','PORTION'})

    def test_foreign_tenant_product_not_found(self):
        self.load()
        with self.sessions.begin() as db:
            state=SalesSyncState(tenant_id='other',source_id=self.source_id,source_timezone='Asia/Yekaterinburg',history_from=date(2026,9,1),backfill_next=date(2026,9,1))
            db.add(state);db.flush()
            batch=ProductKnowledgeBatch(tenant_id='other',source_id=self.source_id,plan_hash='b'*64,report={},initial_status='ON_SALE',created_by_user_id=1)
            db.add(batch);db.flush()
            p=ProductKnowledgeProduct(tenant_id='other',source_id=self.source_id,iiko_product_id=self.product,batch_id=batch.id,
                name='Чужое изделие',unit_id=self.unit,unit_name='шт',sale_mode='UNKNOWN',sale_status='ON_SALE',source_deleted=False,
                observed_at=self.snapshot.observed_at,provenance={},published=True)
            db.add(p);db.flush();foreign=p.id
        self.assertEqual(self.client.get('/products/'+str(foreign)).status_code,404)
        self.assertEqual(self.client.get('/products').json()['total'],2)

    def test_seller_prices_only_primary_point(self):
        from app.models.supply import Department
        from app.models.employee import IikoDepartmentMapping
        self.load()
        with self.sessions.begin() as db:
            other=Department(tenant_id='eclair',code='OTHER',name='Другая точка',business_type='RETAIL_POINT')
            db.add(other);db.flush();other_id=other.id
            db.add(IikoDepartmentMapping(tenant_id='eclair',iiko_department_id=uuid4(),olap_department_id=uuid4(),eos_department_id=other.id,reason='confirmed test',decided_by_user_id=1))
            product=db.scalar(select(ProductKnowledgeProduct))
            for point in [self.department_id,other_id]:
                db.add(ProductKnowledgePrice(tenant_id='eclair',product_id=product.id,department_id=point,valid_from=date(2026,10,1),valid_to=date(2026,11,1),amount=140,currency='RUB',price_unit='шт',evidence='verified test',verified_by_user_id=1,observed_at=self.snapshot.observed_at))
            for role in db.scalars(select(EmployeeRoleAssignment)):role.role=EmployeeRole.SELLER
        self.assertEqual(self.client.get('/products').status_code,403)
        self.assertEqual(self.client.get('/products?department_id='+str(other_id)).status_code,403)

    def test_business_reader_roles_and_production_assignment(self):
        from app.models.supply import Department
        self.load()
        for role in (EmployeeRole.NETWORK_MANAGER, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR):
            with self.sessions.begin() as db:
                for assignment in db.scalars(select(EmployeeRoleAssignment)):assignment.role=role
            self.assertEqual(self.client.get('/products').status_code,200,role)
        for role in (EmployeeRole.CHEF_CONFECTIONER, EmployeeRole.HEAD_OF_PRODUCTION):
            with self.sessions.begin() as db:
                db.get(Department,self.department_id).business_type='RETAIL_POINT'
                for assignment in db.scalars(select(EmployeeRoleAssignment)):assignment.role=role
            self.assertEqual(self.client.get('/products').status_code,403,role)
            with self.sessions.begin() as db:db.get(Department,self.department_id).business_type='PRODUCTION'
            self.assertEqual(self.client.get('/products').status_code,200,role)

    def test_sales_product_link_requires_same_confirmed_mapping(self):
        from app.models.supply import SupplyProduct
        from app.models.sales import SalesFact
        with self.sessions.begin() as db:
            unit=SupplyUnit(tenant_id='eclair',code='TST',name_ru='Штука',short_name_ru='шт')
            db.add(unit);db.flush()
            other=SupplyProduct(tenant_id='eclair',name='Другое изделие',normalized_name='другое изделие',iiko_id=str(uuid4()),default_unit_id=unit.id)
            db.add(other);db.flush()
            for fact in db.scalars(select(SalesFact).where(SalesFact.iiko_product_id==self.product)):fact.product_id=other.id
        plan=self.plan()
        self.assertEqual(plan['conflicts'],1)
        self.assertIn('SALES_PRODUCT_MAPPING_DISAGREEMENT',next(p for p in plan['rows'] if p['iiko_product_id']==str(self.product))['problems'])
