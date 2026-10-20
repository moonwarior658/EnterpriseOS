import unittest
from app.product_knowledge.catalog_order import ordered

class ProductCatalogOrderTests(unittest.TestCase):
    def test_verified_costs_only_zero_is_known_and_missing_last_both_ways(self):
        rows=[dict(id=str(i),name=str(i),cost=c) for i,c in enumerate([dict(status='UNVERIFIED',amount='9999'),dict(status='VERIFIED',amount='0'),dict(status='VERIFIED',amount='100'),dict(status='VERIFIED',amount='9'),None])]
        self.assertEqual([r['id'] for r in ordered(rows,'cost')],['1','3','2','0','4'])
        self.assertEqual([r['id'] for r in ordered(rows,'cost',True)],['2','3','1','0','4'])
    def test_conflicting_prices_are_not_used_and_decimal_precision_is_preserved(self):
        rows=[dict(id='a',name='А',price=dict(department_id='point',amount='999'),price_conflict_points=['point']),dict(id='b',name='Б',price=dict(department_id='point',amount='10.000000000000000001')),dict(id='c',name='В',price=dict(department_id='point',amount='10.000000000000000002'))]
        self.assertEqual([r['id'] for r in ordered(rows,'price')],['b','c','a'])
        self.assertEqual([r['id'] for r in ordered(rows,'price',True)],['c','b','a'])
