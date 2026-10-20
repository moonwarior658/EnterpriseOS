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
    def test_observed_type_and_document_type_pairs(self):
        self.assertEqual(self.usage([self.row(type='INVOICE',documentType='INCOMING_INVOICE')])['categories']['RECEIPT'],'-2')
        self.assertEqual(self.usage([self.row(type='INVENTORY_CORRECTION',documentType='INCOMING_INVENTORY')])['categories']['INVENTORY'],'-2')
        self.assertEqual(self.usage([self.row(type='INVOICE',documentType='UNKNOWN')])['status'],'BLOCKED')

    def test_report_error_or_pagination_never_means_empty(self):
        for value in ['<error/>','<storeReportItemDtoes><hasMore>true</hasMore></storeReportItemDtoes>']:
            with self.assertRaises(ValueError):parse_xml(value,'storeReportItemDtoes','storeReportItemDto')

class BoundedUsageClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_disjoint_windows_preserve_shared_xml_security_limit(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from xml.etree import ElementTree as ET
        from app.integrations.iiko.client import IikoServerClient
        async def xml(path,**kw):return ET.Element('storeReportItemDtoes' if path.endswith('storeOperations') else 'outgoingInvoiceDtoes')
        fake=SimpleNamespace(_get_xml=AsyncMock(side_effect=xml),_get_json_list=AsyncMock(return_value=[]))
        result=await IikoServerClient.get_raw_material_usage_inputs(fake,start=date(2026,9,1),end=END,warehouse_id=WAREHOUSE)
        self.assertEqual(fake._get_xml.await_count,10);self.assertEqual(fake._get_json_list.await_count,2)
        requests=[call.kwargs['params'] for call in fake._get_xml.await_args_list if call.args[0].endswith('storeOperations')]
        self.assertEqual([r['dateFrom'] for r in requests],['01.09.2026','08.09.2026','15.09.2026','22.09.2026','29.09.2026'])
        self.assertEqual([r['dateTo'] for r in requests],['07.09.2026','14.09.2026','21.09.2026','28.09.2026','30.09.2026'])
        with self.assertRaises(ValueError):await IikoServerClient.get_raw_material_usage_inputs(fake,start=START,end=END,warehouse_id=WAREHOUSE)
        fake._get_xml=AsyncMock(return_value=ET.Element('error'))
        with self.assertRaises(Exception):await IikoServerClient.get_raw_material_usage_inputs(fake,start=date(2026,9,1),end=END,warehouse_id=WAREHOUSE)
