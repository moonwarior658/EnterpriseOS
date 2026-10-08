"""Dedicated temporary PG: concurrent retries, constraints and downgrade safety."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine, select, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from app.models.user import User
from app.models.employee import Employee, EmployeeRoleAssignment, IikoDepartmentMapping
from app.models.supply import Department
from app.models.sales import SalesSyncState, SalesDaySync
from app.models.product_knowledge import ProductKnowledgeProduct
from app.product_knowledge.bootstrap import preview, publish, rollback_publication
from app.schemas.product_knowledge import SourceSnapshot
from app.sales.service import ingest_day
from alembic import command
from alembic.config import Config
from app.core.config import settings
URL=os.getenv('PRODUCT_KNOWLEDGE_TEST_DATABASE_URL')


@unittest.skipUnless(URL,'PRODUCT_KNOWLEDGE_TEST_DATABASE_URL not configured')
class ProductKnowledgePostgresTests(unittest.TestCase):
    def setUp(self):
        url=make_url(URL)
        if url.host!='127.0.0.1' or url.database!='eos_supply_migration_test' or url.port!=55439:
            raise RuntimeError('Dedicated K1 temporary PostgreSQL required')
        self.engine=create_engine(URL);self.sessions=sessionmaker(self.engine,expire_on_commit=False)
        self.tenant='k1-'+uuid4().hex[:12];self.source='a'*64;product,second,unit,point=uuid4(),uuid4(),uuid4(),uuid4()
        now=datetime.now(timezone.utc)
        with self.sessions.begin() as db:
            user=User(username=self.tenant,display_name='Fixture admin',hashed_password='x',tenant_id=self.tenant,is_active=True,is_admin=True)
            db.add(user);db.flush();self.actor=user.id
            department=Department(tenant_id=self.tenant,code='TEST',name='Fixture point',business_type='RETAIL_POINT')
            db.add(department);db.flush();self.department=department.id
            employee=Employee(tenant_id=self.tenant,linked_user_id=self.actor,full_name='Fixture admin',birth_date=date(1990,1,1),phone='0',residence_address='test')
            db.add(employee);db.flush()
            db.add(EmployeeRoleAssignment(tenant_id=self.tenant,employee_id=employee.id,role='ADMIN',valid_from=now-timedelta(days=1),reason='fixture',assigned_by_user_id=self.actor))
            db.add(IikoDepartmentMapping(tenant_id=self.tenant,iiko_department_id=uuid4(),olap_department_id=point,eos_department_id=self.department,reason='explicit fixture',decided_by_user_id=self.actor))
            state=SalesSyncState(tenant_id=self.tenant,source_id=self.source,source_timezone='Asia/Yekaterinburg',history_from=date(2026,9,1),backfill_next=date(2026,10,1))
            db.add(state);db.flush()
            for n in range(30):db.add(SalesDaySync(tenant_id=self.tenant,source_id=self.source,business_date=date(2026,9,1)+timedelta(days=n),last_success_at=now,row_count=0))
            db.flush()
            rows=[{'Department.Id':str(point),'UniqOrderId.Id':str(uuid4()),'ItemSaleEvent.Id':str(uuid4()),'DishId':str(p),
                'OpenDate.Typed':'2026-09-15','OpenTime':'2026-09-15T10:00:00','CloseTime':'2026-09-15T10:01:00','DishName':'Эклер',
                'DishAmountInt':1,'DishSumInt':140,'DishDiscountSumInt':140,'DishReturnSum':0,'Storned':'FALSE','OrderDeleted':'NOT_DELETED','DeletedWithWriteoff':'NOT_DELETED'} for p in [product,second]]
            ingest_day(db,rows,state=state,day=date(2026,9,15),department_ids=[point],seen_at=now)
        snapshot=SourceSnapshot(source_id=self.source,observed_at=now,evidence='fixture',complete=True,
            products=[dict(id=p,name='Эклер',main_unit=unit,unit_weight_kg='0.05000000001',deleted=False,source_type='DISH',use_balance_for_sell=False) for p in [product,second]],units=[dict(id=unit,name='шт')])
        with self.sessions() as db:self.plan=preview(db,self.tenant,self.source,snapshot)

    def tearDown(self):self.engine.dispose()

    def load(self):
        with self.sessions.begin() as db:return publish(db,db.get(User,self.actor),self.plan,expected_hash=self.plan['plan_hash'],initial_status='ON_SALE',confirmed_point_ids=[self.department]).id

    def test_concurrent_retry_constraints_weight_and_rollback(self):
        with ThreadPoolExecutor(max_workers=2) as executor:ids=list(executor.map(lambda _:self.load(),range(2)))
        self.assertEqual(ids[0],ids[1])
        with self.sessions() as db:
            rows=list(db.scalars(select(ProductKnowledgeProduct).where(ProductKnowledgeProduct.tenant_id==self.tenant)))
            self.assertEqual(len(rows),2);self.assertEqual(str(rows[0].unit_weight_kg),'0.05000000001')
            values={c.name:getattr(rows[0],c.name) for c in ProductKnowledgeProduct.__table__.columns if c.name!='id'}
        for change in ({},{'iiko_product_id':uuid4(),'tenant_id':'foreign'},{'iiko_product_id':uuid4(),'sale_status':'UNKNOWN'}):
            with self.assertRaises(IntegrityError):
                with self.sessions.begin() as db:db.add(ProductKnowledgeProduct(**{**values,**change}));db.flush()
        with self.sessions.begin() as db:rollback_publication(db,db.get(User,self.actor),ids[0])
        with self.sessions() as db:self.assertFalse(any(p.published for p in db.scalars(select(ProductKnowledgeProduct).where(ProductKnowledgeProduct.tenant_id==self.tenant))))
        self.assertIn('ck_pk_sale_mode',{c['name'] for c in inspect(self.engine).get_check_constraints('product_knowledge_products')})

    def test_downgrade_refuses_populated_catalog(self):
        self.load();url=make_url(URL)
        previous=(settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port)
        try:
            settings.postgres_db=url.database;settings.postgres_user=url.username;settings.postgres_password=url.password or '';settings.postgres_host=url.host;settings.postgres_port=url.port
            with self.assertRaisesRegex(RuntimeError,'PRODUCT_KNOWLEDGE_DATA_EXISTS'):command.downgrade(Config(str(Path(__file__).parents[1]/'alembic.ini')),'20261006_0073')
            with self.engine.connect() as c:self.assertEqual(c.execute(text('select version_num from alembic_version')).scalar(),'20261008_0074')
        finally:settings.postgres_db,settings.postgres_user,settings.postgres_password,settings.postgres_host,settings.postgres_port=previous
