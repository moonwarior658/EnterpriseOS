import copy, unittest
from datetime import date
from tests.test_material_purchases import document, SUPPLIERS
from app.raw_materials.analytics import average, usage, periods, parse_xml
from app.raw_materials.purchases import WAREHOUSE, TECHNICAL

MAPPING=dict(iiko_product_id='product',unit_id='unit',unit='кг')
START, END=date(2026,4,1),date(2026,10,1)
class CalendarAnalyticsTests(unittest.TestCase):
    def average(self, docs):return average(docs,SUPPLIERS,MAPPING,start=START,end=END,units={})
    def test_weighted_calendar_not_monthly_mean_or_latest_tie(self):
        a=document(dateIncoming='2026-04-01T09:00:00');b=document(dateIncoming='2026-09-30T09:00:00')
        b['items'][0].update(amount='1',actualAmount='1',sum='60')
        self.assertEqual(self.average([a,b])['amount'],'40')
        self.assertEqual(self.average([a,copy.deepcopy(a)])['denominator'],'3')
        # Equal date documents are all included in the average, unlike latest-price selection.
        self.assertEqual(self.average([a,document(dateIncoming='2026-04-01T09:00:00')])['status'],'READY')
        self.assertEqual(self.average([document()])['status'],'NO_DATA')
        self.assertEqual(periods(date(2027,1,31)),(date(2026,7,1),date(2027,1,1),date(2026,12,1)))
    def test_bad_historical_unit_blocks_entire_mean_and_technical_excluded(self):
        row=document(dateIncoming='2026-04-01T09:00:00');row['items'][0]['amountUnit']='PCS'
        self.assertEqual(self.average([row])['status'],'BLOCKED')
        self.assertIsNone(self.average([row])['amount'])
        self.assertEqual(self.average([document(id=TECHNICAL,dateIncoming='2026-04-01T09:00:00')])['status'],'NO_DATA')
    def usage(self,rows,docs=None,opening='10',closing='8'):
        return usage(rows,docs or [dict(id='doc',status='PROCESSED',defaultStoreId=WAREHOUSE,items=[dict(productId='dish')])],{'dish':'DISH'},MAPPING,start=date(2026,9,1),end=END,opening=opening,closing=closing)
    def row(self,**changes):
        row=dict(product='product',primaryStore=WAREHOUSE,amount='-2',date='01.09.2026',type='OUTGOING_INVOICE',documentId='doc',documentNum='42');row.update(changes);return row
    def test_usage_direct_vs_production_and_reversal(self):
        self.assertEqual(self.usage([self.row()])['quantity'],'2')
        docs=[dict(id='doc',status='PROCESSED',defaultStoreId=WAREHOUSE,items=[dict(productId='product')])]
        result=self.usage([self.row()],docs)
        self.assertEqual(result['quantity'],'0');self.assertEqual(result['categories']['DIRECT_ISSUE'],'-2')
        self.assertEqual(self.usage([self.row(amount='2')],closing='12')['quantity'],'-2')
    def test_unknown_is_not_zero_and_inventory_is_not_production(self):
        self.assertIsNone(self.usage([self.row()],opening=None)['quantity'])
        self.assertIn('BALANCE_MISMATCH',self.usage([self.row()],closing='9')['reasons'])
        self.assertEqual(self.usage([self.row(type='INCOMING_INVENTORY')])['quantity'],'0')
        self.assertIsNone(self.usage([self.row()],docs=[dict(id='doc',status='NEW',items=[])])['quantity'])
        self.assertIsNone(self.usage([self.row(amount='NaN')])['quantity'])
        self.assertEqual(self.usage([],opening='0',closing='0')['quantity'],'0')
    def test_report_error_or_pagination_never_means_empty(self):
        for value in ['<error/>','<storeReportItemDtoes><hasMore>true</hasMore></storeReportItemDtoes>']:
            with self.assertRaises(ValueError):parse_xml(value,'storeReportItemDtoes','storeReportItemDto')
