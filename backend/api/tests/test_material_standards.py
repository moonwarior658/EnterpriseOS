import copy, unittest
from datetime import date
from uuid import uuid4
from sqlalchemy import select
from tests import test_raw_materials as fixture
from tests.test_material_purchases import document, SUPPLIERS
from app.models.raw_material import MaterialProductAllowance, MaterialUnitConversion
from app.models.iiko import IikoUnitMapping
from app.models.employee import EmployeeRole
from app.raw_materials.purchases import evaluate
from app.schemas.raw_materials import Knowledge

class StandardPolicyTests(unittest.TestCase):
    def test_only_exact_approved_scope_and_effective_period_converts(self):
        mapping=dict(iiko_product_id='product',unit_id='kg',unit='кг',specification_hash='approved',conversions=[dict(from_unit_id='pcs',to_unit_id='kg',supplier_iiko_id='supplier',container_id=None,factor='0.5',valid_from='2026-04-01',valid_to='2026-10-01',packaging='Пачка',evidence='Этикетка')])
        def run(day='2026-09-30T09:00:00',supplier='supplier'):
            return evaluate([document(unit='pcs',dateIncoming=day,supplier=supplier)],SUPPLIERS,mapping,date_from='2026-04-01',date_to='2026-11-01')
        result=run();self.assertEqual(result['status'],'READY');self.assertEqual(result['candidates'][0]['denominator'],'1.5')
        self.assertEqual(result['candidates'][0]['lines'][0]['original_line']['amountUnit'],'pcs')
        self.assertEqual(run(day='2026-10-01T09:00:00')['status'],'BLOCKED')
        self.assertEqual(run(supplier='other')['status'],'BLOCKED')
        mapping['conversions'].append(copy.deepcopy(mapping['conversions'][0]));self.assertEqual(run()['status'],'BLOCKED')
    def test_overlapping_coefficients_nonfinite_and_duplicate_primary_rejected(self):
        c=dict(from_unit_id=str(uuid4()),to_unit_id=str(uuid4()),supplier_iiko_id=str(uuid4()),factor='0.5',valid_from='2026-04-01',valid_to='2026-10-01',packaging='Пачка',evidence='Этикетка')
        with self.assertRaises(ValueError):Knowledge(conversions=[c,c])
        for factor in ('NaN','Infinity','0','-1'):
            with self.assertRaises(ValueError):Knowledge(conversions=[dict(c,factor=factor)])

class StandardFlowTests(unittest.TestCase):
    seed=fixture.RawMaterialTests.seed
    bind_client=fixture.RawMaterialTests.bind_client
    enroll=fixture.RawMaterialTests.enroll
    role=fixture.RawMaterialTests.role
    tearDown=fixture.RawMaterialTests.tearDown
    def setUp(self):
        fixture.RawMaterialTests.setUp(self)
        MaterialProductAllowance.__table__.create(self.engine);MaterialUnitConversion.__table__.create(self.engine)
        self.enroll();self.path='/raw-materials/'+str(self.product)
    def save_standard(self,**changes):
        knowledge=dict(manufacturer='БМК',approved_products=[dict(product_id=str(self.second),role='PRIMARY',manufacturer='Ларица',restrictions='Только согласованное применение',evidence='Решение снабжения'),dict(product_id=str(self.product),role='RESERVE',manufacturer='БМК',restrictions='Согласованная замена',evidence='Проверка кондитеров')])
        knowledge.update(changes)
        return self.client.patch(self.path+'/knowledge',json=dict(expected_version=self.client.get(self.path).json()['version'],reason='Консультация с кондитерами',knowledge=knowledge))
    def confirm_standard(self):
        body=self.client.get(self.path).json();latest=body['latest']
        return self.client.post(self.path+'/knowledge/confirm',json=dict(expected_version=body['version'],reason='Версия проверена',specification_id=latest['id'],content_hash=latest['content_hash'],primary_product_id=str(self.second)))
    def test_main_reserve_selection_new_revision_preserves_approved_version(self):
        r=self.save_standard();self.assertEqual(r.status_code,200,r.text)
        r=self.confirm_standard();self.assertEqual(r.status_code,200,r.text);body=r.json()
        self.assertEqual(body['current']['primary_product_id'],str(self.second));self.assertEqual(len(body['reserves']),1)
        selected=self.client.post(self.path+'/reserve-selection',json=dict(expected_version=body['version'],reason='Основной временно недоступен',specification_id=body['current']['id'],target_product_id=str(self.product)))
        self.assertEqual(selected.status_code,200,selected.text);self.assertEqual(selected.json()['current']['primary_product_id'],str(self.second))
        self.assertEqual(self.save_standard(manufacturer='Новая версия').status_code,200)
        body=self.client.get(self.path).json();self.assertNotEqual(body['latest']['id'],body['current']['id']);self.assertEqual(body['current']['knowledge']['manufacturer'],'БМК')
        self.role(EmployeeRole.CHEF_CONFECTIONER)
        self.assertEqual(self.client.post(self.path+'/reserve-selection',json=dict(expected_version=body['version'],reason='Недоступно',specification_id=body['current']['id'],target_product_id=str(self.product))).status_code,403)
    def test_cross_tenant_targets_and_unapproved_reserve_rejected(self):
        product=dict(product_id=str(self.foreign),role='PRIMARY',manufacturer='Чужой',restrictions='',evidence='Основание')
        self.assertEqual(self.save_standard(approved_products=[product]).status_code,409)
        self.save_standard();self.confirm_standard();body=self.client.get(self.path).json()
        self.assertEqual(self.client.post(self.path+'/reserve-selection',json=dict(expected_version=body['version'],reason='Не разрешено',specification_id=body['current']['id'],target_product_id=str(self.second))).status_code,409)

    def test_nested_future_money_fields_are_redacted_from_knowledge_history(self):
        from app.models.raw_material import MaterialSpecificationVersion
        self.save_standard()
        with self.sessions.begin() as db:
            row=db.scalar(select(MaterialSpecificationVersion));payload=copy.deepcopy(row.payload)
            payload['approved_products'][0]['purchase_price']='SECRET_73129'
            row.payload=payload
        self.role(EmployeeRole.CHEF_CONFECTIONER)
        for path in (self.path,self.path+'/history'):
            response=self.client.get(path);self.assertEqual(response.status_code,200,response.text);self.assertNotIn('SECRET_73129',response.text)
