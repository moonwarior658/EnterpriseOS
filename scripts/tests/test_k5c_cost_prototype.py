import copy
from datetime import date
from decimal import Decimal
import unittest

from scripts.k5c_cost_prototype import calculate


def fixture():
    return dict(key='cake', references=[dict(key='cake',type='DISH'), dict(key='dough',type='PREPARED'),
        dict(key='flour',type='GOODS'), dict(key='box',type='GOODS')],
        charts=[dict(root_key='cake',dateFrom='2026-01-01',dateTo=None,writeoff='ASSEMBLE',assembledAmount=2,
            items=[dict(product_key='dough',amountIn='0.5'), dict(product_key='box',amountIn=2)]),
            dict(root_key='dough',dateFrom='2026-01-01',dateTo=None,writeoff='ASSEMBLE',assembledAmount=1,
                items=[dict(product_key='flour',amountIn='1.5')])],
        balances=[dict(rows=[dict(product_key='flour',store_key='A',amount='10',sum='300'),
            dict(product_key='box',store_key='A',amount=5,sum='25')])])


class CostPrototypeTests(unittest.TestCase):
    def run_cost(self, root=None, **kwargs):
        return calculate(root or fixture(),at=date(2026,10,9),**kwargs)

    def test_batch_basis_and_nested_gross(self):
        result=self.run_cost()
        self.assertEqual(Decimal(result['diagnostic_amount']),Decimal('16.25'))
        self.assertIsNone(result['amount'])
        self.assertFalse(result['publication_allowed'])

    def test_missing_leaf_never_becomes_zero(self):
        root=fixture(); root['balances'][0]['rows'].pop()
        self.assertIsNone(self.run_cost(root)['diagnostic_amount'])

    def test_source_zero_money_is_distinct_from_missing(self):
        root=fixture(); root['balances'][0]['rows'][1]['sum']=0
        self.assertEqual(Decimal(self.run_cost(root)['diagnostic_amount']),Decimal('11.25'))

    def test_zero_norm_does_not_require_cost(self):
        root=fixture(); root['charts'][0]['items'][1]['amountIn']=0; root['balances'][0]['rows'].pop()
        self.assertIsNotNone(self.run_cost(root)['diagnostic_amount'])

    def test_zero_quantity_and_negative_only_are_unavailable(self):
        for quantity in ('0','-2'):
            root=fixture(); root['balances'][0]['rows'][1]['amount']=quantity
            self.assertIsNone(self.run_cost(root)['diagnostic_amount'])

    def test_positive_pool_is_weighted_and_explicit(self):
        root=fixture(); root['balances'][0]['rows'].append(dict(product_key='flour',store_key='B',amount=20,sum=1200))
        self.assertEqual(Decimal(self.run_cost(root)['diagnostic_amount']),Decimal('23.75'))
        self.assertEqual(Decimal(self.run_cost(root,store_key='A')['diagnostic_amount']),Decimal('16.25'))
        self.assertIn('ALL_STORES_POOL',self.run_cost(root)['warnings'])

    def test_negative_stock_is_flagged_not_silently_used(self):
        root=fixture(); root['balances'][0]['rows'].append(dict(product_key='flour',store_key='B',amount=-2,sum=-80))
        result=self.run_cost(root)
        self.assertEqual(Decimal(result['diagnostic_amount']),Decimal('16.25'))
        self.assertIn('NONPOSITIVE_STOCK_PRESENT',result['warnings'])

    def test_direct_child_uses_stock_not_recursive_recipe(self):
        root=fixture(); root['charts'][1]['writeoff']='DIRECT'
        root['balances'][0]['rows'].append(dict(product_key='dough',store_key='A',amount=3,sum=180))
        self.assertEqual(Decimal(self.run_cost(root)['diagnostic_amount']),Decimal('20'))

    def test_cycle_and_ambiguous_version_fail_closed(self):
        root=fixture(); root['charts'][1]['items'][0]['product_key']='cake'
        self.assertIsNone(self.run_cost(root)['diagnostic_amount'])
        root=fixture(); root['charts'].append(copy.deepcopy(root['charts'][0]))
        self.assertIsNone(self.run_cost(root)['diagnostic_amount'])

    def test_specific_scope_requires_resolver(self):
        root=fixture(); root['charts'][0]['items'][0]['storeSpecification']={'departments':['D'],'inverse':False}
        self.assertIsNone(self.run_cost(root)['diagnostic_amount'])

    def test_unknown_nested_policy_is_unavailable(self):
        root=fixture(); root['charts'][1]['writeoff']='UNKNOWN'
        self.assertIsNone(self.run_cost(root)['diagnostic_amount'])

    def test_invalid_numbers_and_duplicate_rows_fail_closed(self):
        for value in (None,'NaN','Infinity',1.2):
            root=fixture(); root['balances'][0]['rows'][0]['sum']=value
            self.assertIsNone(self.run_cost(root)['diagnostic_amount'])
        root=fixture(); root['balances'][0]['rows'].append(copy.deepcopy(root['balances'][0]['rows'][0]))
        self.assertIsNone(self.run_cost(root)['diagnostic_amount'])


if __name__=='__main__':
    unittest.main()
