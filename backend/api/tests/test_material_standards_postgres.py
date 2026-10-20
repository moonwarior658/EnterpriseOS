import os, unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from app.models.user import User
from app.models.raw_material import MaterialProductAllowance as Allowance, MaterialUnitConversion as Conversion
from app.schemas.raw_materials import SaveKnowledge, Knowledge
from app.raw_materials import service
from tests import test_raw_materials_postgres as fixture

@unittest.skipUnless(os.getenv('RAW_MATERIAL_TEST_DATABASE_URL'),'Disposable PG not configured')
class StandardPostgresTests(unittest.TestCase):
    setUpClass=classmethod(fixture.RawMaterialPostgresTests.setUpClass.__func__)
    tearDown=fixture.RawMaterialPostgresTests.tearDown
    enroll=fixture.RawMaterialPostgresTests.enroll
    def setUp(self):
        fixture.RawMaterialPostgresTests.setUp(self);self.enroll()
        with self.sessions.begin() as db:
            body=service.save(db,db.get(User,self.actor_id),self.product,SaveKnowledge(expected_version=1,reason='Проверка стандарта',knowledge=Knowledge()))
            self.spec=body['latest']['id']
    def allowance(self,target,role='RESERVE'):
        return Allowance(tenant_id=self.tenant,product_id=self.product,specification_id=self.spec,target_product_id=target,role=role)
    def test_tenant_fk_single_primary_and_immutable(self):
        with self.assertRaises(DBAPIError):
            with self.sessions.begin() as db:db.add(self.allowance(self.foreign));db.flush()
        with self.sessions.begin() as db:db.add(self.allowance(self.product,'PRIMARY'))
        with self.assertRaises(DBAPIError):
            with self.sessions.begin() as db:db.add(self.allowance(self.second,'PRIMARY'));db.flush()
        with self.assertRaises(DBAPIError):
            with self.sessions.begin() as db:
                row=db.scalar(select(Allowance).where(Allowance.specification_id==self.spec));row.role='RESERVE';db.flush()
    def test_concurrent_overlap_and_history_guard(self):
        from_id,to_id,supplier=uuid4(),uuid4(),uuid4()
        def insert(_):
            try:
                with self.sessions.begin() as db:
                    db.add(Conversion(tenant_id=self.tenant,product_id=self.product,specification_id=self.spec,from_unit_id=from_id,to_unit_id=to_id,supplier_iiko_id=supplier,container_id=None,factor='0.5',valid_from=date(2026,4,1),valid_to=date(2026,10,1)));db.flush()
                return True
            except DBAPIError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(insert,[1,2]))
        self.assertEqual(sum(results),1)
        with self.assertRaises(DBAPIError):
            with self.sessions.begin() as db:db.delete(db.scalar(select(Conversion).where(Conversion.specification_id==self.spec)));db.flush()
    def test_approval_prevents_late_insert(self):
        from app.schemas.raw_materials import Confirm
        with self.sessions.begin() as db:
            actor=db.get(User,self.actor_id);body=service.detail(db,actor,self.product);row=body['latest']
            service.confirm(db,actor,self.product,Confirm(expected_version=body['version'],reason='Подтверждено',specification_id=row['id'],content_hash=row['content_hash'],primary_product_id=self.product))
        with self.assertRaises(DBAPIError):
            with self.sessions.begin() as db:db.add(self.allowance(self.second));db.flush()
