"""Pilot tooling must fail closed on identities and verify actual repeat artifacts."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4
spec=importlib.util.spec_from_file_location('k5b_pilot',Path(__file__).parents[3]/'scripts/k5b_pilot.py')
pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)

class PilotToolTests(unittest.TestCase):
    def test_uuid_resolution_requires_exact_unique_source_keys(self):
        products=[dict(id=str(uuid4()),tenant_id='test',source_id='a'*64,iiko_product_id=str(uuid4()),name='Same name') for _ in range(3)]
        department=dict(tenant_id='test',olap_department_id=str(uuid4()),eos_department_id=str(uuid4()))
        keys=tuple(pilot.key(p['iiko_product_id']) for p in products)
        with patch.object(pilot,'TARGETS',keys),patch.object(pilot,'DEPARTMENT_KEY',pilot.key(department['olap_department_id'])):
            result=pilot.resolve_rows(products,[department])
            self.assertEqual(result['department_id'],department['olap_department_id'])
            self.assertEqual(set(result['products']),set(keys))
            self.assertIsNone(result['warehouse_id'])
            with self.assertRaisesRegex(ValueError,'UUID_NOT_UNIQUE'):pilot.resolve_rows(products+[products[0]],[department])
            with self.assertRaisesRegex(ValueError,'DEPARTMENT_NOT_UNIQUE'):pilot.resolve_rows(products,[])
            products[0]['source_id']='b'*64
            with self.assertRaisesRegex(ValueError,'SOURCE_NOT_UNIQUE'):pilot.resolve_rows(products,[department])
    def test_repeat_checks_scope_versions_quality_and_unchanged_business(self):
        first=dict(status='succeeded',execution_id=str(uuid4()),payload={'effective_on':'2026-10-09'},
            observations=[dict(id=str(uuid4()),product_id='product',status='INCOMPLETE',payload={'manifest_hash':'hash'})],
            versions=[{'id':'version'}],protected={'catalog':'hash'})
        second=copy.deepcopy(first);second['execution_id']=str(uuid4());second['observations'][0]['id']=str(uuid4())
        self.assertTrue(pilot.compare_runs(first,second)['passed'])
        second['observations'][0]['payload']['manifest_hash']='changed'
        self.assertFalse(pilot.compare_runs(first,second)['passed'])
        second=copy.deepcopy(first)
        with self.assertRaisesRegex(ValueError,'REPEAT_SCOPE_INVALID'):pilot.compare_runs(first,second)
        second['execution_id']=str(uuid4());second['payload']['effective_on']='2026-05-31'
        with self.assertRaisesRegex(ValueError,'REPEAT_SCOPE_INVALID'):pilot.compare_runs(first,second)
