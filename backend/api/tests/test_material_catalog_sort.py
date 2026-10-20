"""Sorting must never treat an unknown purchase fact as zero."""
import unittest
from app.raw_materials.catalog_sort import ordered


class MaterialCatalogSortTests(unittest.TestCase):
    def test_decimal_order_and_separate_quality_states_in_both_directions(self):
        rows=[dict(id=str(i),name=name,last_purchase_price=dict(status=status,amount=amount)) for i,(name,status,amount) in enumerate([
            ('Нет данных','NO_DATA',None),('Блокировка','BLOCKED','9999'),('Сто','READY','100'),('Десять','READY','10.0000000000000000002'),('Почти десять','READY','10.0000000000000000001'),('Ноль','READY','0')])]
        self.assertEqual([r['name'] for r in ordered(rows,'last_purchase_price')],['Ноль','Почти десять','Десять','Сто','Блокировка','Нет данных'])
        self.assertEqual([r['name'] for r in ordered(rows,'last_purchase_price',True)],['Сто','Десять','Почти десять','Ноль','Блокировка','Нет данных'])

    def test_ambiguous_supplier_and_missing_weight_last_even_descending(self):
        rows=[dict(id='a',name='А',backup_supplier={'name':'Я'},backup_ambiguous=True,unit_weight_kg=None),dict(id='b',name='Б',backup_supplier={'name':'Б'},unit_weight_kg='10'),dict(id='c',name='В',backup_supplier={'name':'А'},unit_weight_kg='2')]
        self.assertEqual([r['id'] for r in ordered(rows,'backup_supplier')],['c','b','a'])
        self.assertEqual([r['id'] for r in ordered(rows,'backup_supplier',True)],['b','c','a'])
        self.assertEqual([r['id'] for r in ordered(rows,'unit_weight_kg',True)],['b','c','a'])
