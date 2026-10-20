"""Only disposable localhost PG: actual Alembic cycle, tenant constraints and concurrency."""
import os
os.environ.setdefault('POSTGRES_DB','test')
os.environ.setdefault('POSTGRES_USER','test')
os.environ.setdefault('POSTGRES_PASSWORD','test')
os.environ.setdefault('JWT_SECRET_KEY','test-jwt-secret')
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from fastapi import HTTPException
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, DBAPIError
from app.core.config import settings
from app.models.user import User
from app.models.employee import Employee, EmployeeRoleAssignment
from app.models.supply import Department
from app.models.raw_material import RawMaterialProfile as Profile, MaterialSpecificationVersion as Specification, MaterialSpecificationApproval as Approval
from app.schemas.raw_materials import Enroll, SaveKnowledge, Knowledge
from app.raw_materials import service
from tests import test_raw_materials as api_fixture

URL=os.getenv('RAW_MATERIAL_TEST_DATABASE_URL')

@contextmanager
def migration_settings(url):
    previous={key:getattr(settings,key) for key in ('postgres_db','postgres_user','postgres_password','postgres_host','postgres_port')}
    try:
        for key,value in dict(postgres_db=url.database,postgres_user=url.username,postgres_password=url.password or '',postgres_host=url.host,postgres_port=url.port).items():setattr(settings,key,value)
        yield
    finally:
        for key,value in previous.items():setattr(settings,key,value)


@unittest.skipUnless(URL,'RAW_MATERIAL_TEST_DATABASE_URL not configured')
class RawMaterialPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url=make_url(URL)
        if cls.url.host!='127.0.0.1' or cls.url.port!=55439 or cls.url.database!='eos_supply_migration_test':
            raise RuntimeError('Dedicated disposable R-M1 PostgreSQL required')
        with migration_settings(cls.url):
            command.upgrade(Config('alembic.ini'),'head')
            # Re-running tests must never delete earlier fixture history.
            engine=create_engine(URL)
            try:
                with engine.connect() as connection:
                    populated=connection.execute(text('SELECT EXISTS (SELECT 1 FROM raw_material_profiles)')).scalar()
            finally:
                engine.dispose()
            if not populated:
                command.downgrade(Config('alembic.ini'),'20261009_0079')
                command.upgrade(Config('alembic.ini'),'head')

    def setUp(self):
        self.engine=create_engine(URL);self.sessions=sessionmaker(self.engine,expire_on_commit=False)
        self.tenant='rm1-'+uuid4().hex[:12];self.department_id=uuid4();self.admin_employee_id=uuid4()
        with self.sessions.begin() as db:
            actor=User(tenant_id=self.tenant,username=self.tenant,display_name='R-M1 fixture',hashed_password='test',is_active=True,is_admin=False)
            db.add(actor);db.flush();self.actor_id=actor.id
            db.add(Department(id=self.department_id,tenant_id=self.tenant,code='PROD',name='Тестовый цех',business_type='PRODUCTION'));db.flush()
            db.add(Employee(id=self.admin_employee_id,tenant_id=self.tenant,linked_user_id=actor.id,full_name='Тестовый снабженец',birth_date=date(1990,1,1),phone='0',residence_address='fixture'));db.flush()
            db.add(EmployeeRoleAssignment(tenant_id=self.tenant,employee_id=self.admin_employee_id,role='SUPPLY_MANAGER',valid_from=datetime.now(timezone.utc)-timedelta(days=1),reason='fixture',assigned_by_user_id=actor.id))
        api_fixture.RawMaterialTests.seed(self)
        api_fixture.RawMaterialTests.bind_client(self)

    tearDown=api_fixture.RawMaterialTests.tearDown
    enroll=api_fixture.RawMaterialTests.enroll
    save=api_fixture.RawMaterialTests.save
    confirm=api_fixture.RawMaterialTests.confirm

    def test_live_api_audit_money_projection_and_immutable_history(self):
        body=self.enroll();saved=self.save();self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(self.confirm().status_code,200)
        with self.sessions() as db:
            spec=db.scalar(select(Specification).where(Specification.product_id==self.product))
            approval=db.scalar(select(Approval).where(Approval.product_id==self.product))
            spec_id=spec.id;approval_id=approval.id
        for table,row_id in [('material_specification_versions',spec_id),('material_specification_approvals',approval_id)]:
            for operation in ['UPDATE '+table+' SET id=id WHERE id=:id','DELETE FROM '+table+' WHERE id=:id']:
                with self.assertRaises(DBAPIError):
                    with self.engine.begin() as connection:connection.execute(text(operation),{'id':row_id})
        with self.sessions.begin() as db:
            role=db.scalar(select(EmployeeRoleAssignment).where(EmployeeRoleAssignment.tenant_id==self.tenant));role.role='CONFECTIONER'
        for path in ['', '/'+str(self.product), '/'+str(self.product)+'/history']:
            result=self.client.get('/raw-materials'+path);self.assertEqual(result.status_code,200,result.text)
            self.assertNotIn('98765',result.text);self.assertNotIn('last_purchase_price',result.text)
        self.assertEqual(self.client.get('/raw-materials?sort=last_purchase_price').status_code,422)
        self.assertEqual(self.client.get('/raw-materials/'+str(self.foreign)).status_code,404)
        with migration_settings(self.url):
            with self.assertRaisesRegex(RuntimeError,'MATERIAL_KNOWLEDGE_EXISTS'):command.downgrade(Config('alembic.ini'),'20261009_0079')
        with self.engine.connect() as connection:self.assertEqual(connection.execute(text('select version_num from alembic_version')).scalar(),'20261020_0080')
        self.assertIn('ck_material_kind',{x['name'] for x in inspect(self.engine).get_check_constraints('raw_material_profiles')})

    def test_tenant_unique_fk_revision_primary_and_approval_constraints(self):
        self.enroll();saved=self.save().json()
        with self.sessions() as db:
            profile=db.get(Profile,self.product)
            spec=db.scalar(select(Specification).where(Specification.product_id==self.product))
            values={c.name:getattr(spec,c.name) for c in Specification.__table__.columns}
        for fields in [dict(product_id=self.product,tenant_id=self.tenant,kind='RAW_MATERIAL',version=1,archived=False,created_by_user_id=self.actor_id),
                       dict(product_id=self.foreign,tenant_id=self.tenant,kind='RAW_MATERIAL',version=1,archived=False,created_by_user_id=self.actor_id),
                       dict(product_id=self.second,tenant_id=self.tenant,kind='INVALID',version=1,archived=False,created_by_user_id=self.actor_id)]:
            with self.assertRaises(IntegrityError):
                with self.sessions.begin() as db:db.add(Profile(**fields));db.flush()
        for change in [dict(id=uuid4()),dict(id=uuid4(),tenant_id='other'),dict(id=uuid4(),revision=0)]:
            with self.assertRaises(IntegrityError):
                with self.sessions.begin() as db:db.add(Specification(**{**values,**change}));db.flush()
        with self.assertRaises(IntegrityError):
            with self.sessions.begin() as db:
                db.add(Approval(tenant_id=self.tenant,product_id=self.product,specification_id=spec.id,primary_product_id=self.second,confirmed_by_user_id=self.actor_id));db.flush()
        self.assertEqual(self.confirm(saved).status_code,200)
        with self.assertRaises(IntegrityError):
            with self.sessions.begin() as db:
                db.add(Approval(tenant_id=self.tenant,product_id=self.product,specification_id=spec.id,primary_product_id=self.product,confirmed_by_user_id=self.actor_id));db.flush()

    def test_concurrent_enrollment_and_stale_draft_are_serialized(self):
        def enroll(_):
            with self.sessions.begin() as db:return service.enroll(db,db.get(User,self.actor_id),Enroll(product_id=self.product,kind='RAW_MATERIAL',reason='Approved fixture'))['id']
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(enroll,range(2)))
        self.assertEqual(results[0],results[1])
        def save(_):
            try:
                with self.sessions.begin() as db:
                    service.save(db,db.get(User,self.actor_id),self.product,SaveKnowledge(expected_version=1,reason='Concurrent fixture',knowledge=Knowledge(purpose='Тест')))
                return 200
            except HTTPException as error:return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,range(2)))
        self.assertEqual(sorted(results),[200,409])
