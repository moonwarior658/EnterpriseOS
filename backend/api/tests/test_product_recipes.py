"""Synthetic K5B pilot; not independent Office acceptance."""
import copy
import os
os.environ.setdefault('POSTGRES_DB','test')
os.environ.setdefault('POSTGRES_USER','test')
os.environ.setdefault('POSTGRES_PASSWORD','test')
os.environ.setdefault('JWT_SECRET_KEY','test-jwt-secret')
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, func
from app.models.product_recipe import ProductRecipeVersion as Version, ProductRecipeObservation as Observation
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from app.models.audit import AuditEvent
from app.integrations.iiko.recipes import read_charts, frozen_json
from app.product_knowledge.recipes import RecipeRefreshPayload, assess, publish_recipes, scope
from tests import test_product_knowledge as k1


def fixture(root=None):
    root, child, goods, unit = root or str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    def chart(pid, ingredient, start='2026-06-01', end=None, amount='0.00000000123456789'):
        return dict(id=str(uuid4()), assembledProductId=pid, dateFrom=start, dateTo=end,
            assembledAmount='1', productWriteoffStrategy='ASSEMBLE', productSizeAssemblyStrategy='COMMON',
            effectiveDirectWriteoffStoreSpecification=None, technologyDescription='Source text', items=[dict(productId=ingredient,
                amountIn=amount, amountMiddle=amount, amountOut=amount, storeSpecification=None, productSizeSpecification=None)])
    current, nested = chart(root, child), chart(child, goods)
    old = chart(root, child, '2025-09-03', '2026-06-01', '0.03')
    prep = dict(id=str(uuid4()), assembledProductId=root, dateFrom='2026-06-01', dateTo=None,
        productSizeAssemblyStrategy='COMMON', items=[dict(productId=goods, amount='0.00000000123456789', storeSpecification=None, productSizeSpecification=None)])
    bundle = dict(tree=dict(assemblyCharts=[current,nested],preparedCharts=[prep]),
        assembled=dict(assemblyCharts=[current]), prepared=dict(preparedCharts=[prep]),
        history={root:[old,current],child:[nested]})
    refs = dict(products={p:dict(id=p,mainUnit=unit,type=t) for p,t in [(root,'DISH'),(child,'PREPARED'),(goods,'GOODS')]},
        units={unit:dict(id=unit,name='kg')}, scales={p:None for p in (root,child,goods)})
    return root, child, bundle, refs

class RecipeQualityTests(unittest.TestCase):
    def setUp(self): self.root,self.child,self.bundle,self.refs=fixture()
    def quality(self): return assess(self.root,date(2026,10,9),self.bundle,self.refs)
    def test_nested_decimal_and_history(self):
        q=self.quality();self.assertEqual(q['status'],'UNCONFIRMED');self.assertFalse(q['ready_for_production'])
        self.assertEqual(len(q['dependencies']),1)
        self.assertEqual(Decimal(self.bundle['tree']['assemblyCharts'][0]['items'][0]['amountIn']),Decimal('0.00000000123456789'))
        history=self.bundle['history'][self.root]
        for day,index in [('2026-05-31',0),('2026-06-01',1)]:
            self.assertEqual([c['id'] for c in history if c['dateFrom'] <= day and (not c['dateTo'] or day<c['dateTo'])],[history[index]['id']])
    def test_missing_unit_base_and_nested(self):
        self.refs['units']={};self.assertIn('UNRESOLVED_UNIT',self.quality()['issues'])
        self.bundle['tree']['assemblyCharts'][0]['assembledAmount']='0';self.assertIn('INVALID_BASE',self.quality()['issues'])
        self.bundle['tree']['assemblyCharts'].pop();self.assertIn('MISSING_NESTED_RECIPE',self.quality()['issues'])
    def test_incomplete_prepared_and_race(self):
        self.bundle['prepared']['preparedCharts']=None;self.assertEqual(self.quality()['status'],'CONFLICT')
        self.bundle['tree']['preparedCharts']=None;self.assertEqual(self.quality()['status'],'INCOMPLETE')
    def test_cycle_and_shared_dependency(self):
        self.bundle['tree']['assemblyCharts'][1]['items'][0]['productId']=self.root
        self.assertIn('RECIPE_CYCLE',self.quality()['issues'])
        self.root,self.child,self.bundle,self.refs=fixture()
        self.bundle['tree']['assemblyCharts'][0]['items']*=2
        self.assertNotIn('RECIPE_CYCLE',self.quality()['issues'])
    def test_unknown_size_overlap_and_boundary(self):
        self.bundle['tree']['assemblyCharts'][0]['productSizeAssemblyStrategy']='SPECIFIC'
        self.assertIn('SIZE_REQUIRES_VERIFICATION',self.quality()['issues'])
        self.bundle['tree']['assemblyCharts'].append(copy.deepcopy(self.bundle['tree']['assemblyCharts'][0]))
        self.assertEqual(self.quality()['status'],'CONFLICT')
        self.bundle['tree']['assemblyCharts'][0]['dateTo']='2026-10-09'
        self.assertIn('INEFFECTIVE_CHART',self.quality()['issues'])
    def test_payload_pilot_and_duplicate(self):
        args=dict(source_id='a'*64,product_ids=[uuid4() for _ in range(6)],department_id=uuid4(),effective_on='2026-10-09',scope_evidence='Confirmed source scope')
        with self.assertRaises(ValueError): RecipeRefreshPayload(**args)
        args['product_ids']=[args['product_ids'][0]]*2
        with self.assertRaises(ValueError): RecipeRefreshPayload(**args)

class RecipePersistenceTests(unittest.TestCase):
    row=k1.ProductKnowledgeTests.row
    ingest=k1.ProductKnowledgeTests.ingest
    plan=k1.ProductKnowledgeTests.plan
    load=k1.ProductKnowledgeTests.load
    tearDown=k1.ProductKnowledgeTests.tearDown
    def setUp(self):
        k1.ProductKnowledgeTests.setUp(self);self.load()
        Version.__table__.create(self.engine);Observation.__table__.create(self.engine)
        root,child,bundle,refs=fixture(str(self.product))
        self.policy=RecipeRefreshPayload(source_id=self.source_id,product_ids=[self.product],department_id=uuid4(),effective_on='2026-10-09',scope_evidence='Fixture explicit department, no warehouse inferred')
        with self.sessions() as db:
            products=scope(db,'eclair',self.policy)
            product=db.get(Product,UUID(products[root]));unit=str(product.unit_id)
            refs['products'][root]['mainUnit']=unit;refs['units'][unit]=dict(id=unit,name=product.unit_name)
        self.collected=dict(products=products,bundles={root:bundle},references=refs,scope=self.policy.model_dump(mode='json'),observed_at=datetime.now(timezone.utc))
        self.execution=uuid4()
    def apply(self, execution=None):
        with self.sessions.begin() as db: return publish_recipes(db,'eclair',self.collected,execution_id=execution or self.execution)
    def test_retry_history_same_uuid_correction_nested_change(self):
        first=self.apply();self.assertEqual(self.apply(),first)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Observation)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Version)),4)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type=='PRODUCT_RECIPES_OBSERVED')),1)
            before=[p.provenance for p in db.scalars(select(Product))]
        self.apply(uuid4())
        nested=self.collected['bundles'][str(self.product)]['tree']['assemblyCharts'][1]
        nested['items'][0]['amountIn']='0.050000000000000001'
        self.apply(uuid4())
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Version)),5)
            self.assertEqual(db.scalar(select(func.count()).select_from(Observation)),3)
            self.assertEqual(before,[p.provenance for p in db.scalars(select(Product))])
    def test_missing_projection_preserves_history(self):
        self.apply();bundle=self.collected['bundles'][str(self.product)]
        bundle['tree']['assemblyCharts']=None;bundle['assembled']['assemblyCharts']=None
        result=self.apply(uuid4());self.assertEqual(result['counts']['INCOMPLETE'],1)
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Version)),4)
    def test_transaction_audit_failure_and_unknown_uuid(self):
        with patch('app.product_knowledge.recipes.record_audit_event',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.apply()
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Observation)),0)
        self.collected['scope']['product_ids']=[str(uuid4())]
        with self.assertRaisesRegex(ValueError,'EXISTING_UUID'):self.apply()

    def test_observed_version_transition_keeps_old_norms(self):
        from app.product_knowledge.recipes import effective_charts
        root=str(self.product);bundle=self.collected['bundles'][root]
        old,current=bundle['history'][root]
        # A dated nested fixture valid on both sides of the K5A boundary.
        bundle['tree']['assemblyCharts'][1]['dateFrom']='2025-01-01'
        bundle['tree']['assemblyCharts'][0]=old
        bundle['assembled']['assemblyCharts']=[old]
        for prepared in bundle['prepared']['preparedCharts']:
            prepared['dateFrom']='2025-01-01'
        self.collected['scope']['effective_on']='2026-05-31'
        first=self.apply()
        self.assertEqual(first['counts']['UNCONFIRMED'],1)
        self.collected['scope']['effective_on']='2026-06-01'
        bundle['tree']['assemblyCharts'][0]=current
        bundle['assembled']['assemblyCharts']=[current]
        second=self.apply(uuid4())
        self.assertEqual(second['counts']['UNCONFIRMED'],1)
        with self.sessions() as db:
            observations=list(db.scalars(select(Observation).order_by(Observation.effective_on)))
            self.assertEqual(len(observations),2)
            self.assertEqual(observations[0].payload['source_responses']['assembled']['assemblyCharts'][0]['items'][0]['amountIn'],'0.03')
            self.assertNotEqual(observations[0].payload['manifest_hash'],observations[1].payload['manifest_hash'])
            self.assertEqual(effective_charts(bundle['history'][root],date(2026,6,1)),[current])

    def test_root_unit_conflict_and_missing_scales(self):
        root=str(self.product)
        self.collected['references']['products'][root]['mainUnit']=str(uuid4())
        result=self.apply();self.assertEqual(result['counts']['CONFLICT'],1)
        with self.sessions() as db:
            observation=db.scalar(select(Observation));self.assertIn('ROOT_UNIT_MISMATCH',observation.payload['issues'])
        self.collected['references']['scales']={}
        result=self.apply(uuid4());self.assertFalse(result['ready_for_production'])

    def test_empty_recipe_and_malformed_items_are_not_ready(self):
        root=str(self.product);bundle=self.collected['bundles'][root]
        bundle['tree']['assemblyCharts'][0]['items']=[None]
        result=self.apply();self.assertFalse(result['ready_for_production'])
        bundle.update(tree=dict(assemblyCharts=None,preparedCharts=None),assembled=dict(assemblyCharts=None),prepared=dict(preparedCharts=None),history={root:[]})
        result=self.apply(uuid4());self.assertEqual(result['counts']['INCOMPLETE'],1)

    def test_collector_explicit_ids_and_separate_projections(self):
        import asyncio
        from app.product_knowledge.recipes import collect_recipes
        root=str(self.product);bundle=self.collected['bundles'][root];refs=self.collected['references']
        client=AsyncMock()
        async def charts(method, **args):
            if method=='getHistory':return bundle['history'][str(args['product_id'])]
            return bundle[{'getTree':'tree','getAssembled':'assembled','getPrepared':'prepared'}[method]]
        client.get_recipe_charts.side_effect=charts
        client.__aenter__.return_value=client
        async def read(client, path, params):
            if path.endswith('products/list'):
                return [{**p,'estimatedPurchasePrice':99} for p in refs['products'].values()]
            if path.endswith('products/productScales'):return refs['scales']
            return list(refs['units'].values())
        with patch('app.product_knowledge.recipes.get_iiko_settings',return_value=object()), \
             patch('app.product_knowledge.recipes.source_identity',return_value=self.source_id), \
             patch('app.product_knowledge.recipes.IikoServerClient',return_value=client), \
             patch('app.product_knowledge.recipes.read_json',side_effect=read):
            result=asyncio.run(collect_recipes(self.sessions,tenant_id='eclair',payload=self.policy,now=datetime.now(timezone.utc)))
        self.assertEqual(result['bundles'],self.collected['bundles'])
        self.assertNotIn('estimatedPurchasePrice',str(result))
        self.assertTrue(all(call.kwargs['department_id']==self.policy.department_id for call in client.get_recipe_charts.call_args_list))

    def test_admin_guard_and_safe_http_errors(self):
        from app.models.employee import EmployeeRoleAssignment, EmployeeRole
        with self.sessions.begin() as db:
            for role in db.scalars(select(EmployeeRoleAssignment)):
                role.role=EmployeeRole.NETWORK_MANAGER
        response=self.client.post('/products/recipes/refresh',json=self.policy.model_dump(mode='json'))
        self.assertEqual(response.status_code,403)
        self.assertNotIn('scope_evidence',response.text)
        self.assertNotIn('Traceback',response.text)

    def test_history_overlap_is_conflict(self):
        bundle=self.collected['bundles'][str(self.product)]
        bundle['history'][str(self.product)][0]['dateTo']=None
        result=self.apply()
        self.assertEqual(result['counts']['CONFLICT'],1)

    def test_source_schedule_disabled(self):
        from app.schemas.automation import validate_automation_schedule_contract,IntervalScheduleConfig
        with self.assertRaisesRegex(ValueError,'manual-only'):
            validate_automation_schedule_contract('products.sync_iiko_recipes',IntervalScheduleConfig(type='interval',minutes=60),self.policy.model_dump(mode='json'))


class ReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_decimal_envelopes_auth_and_safe_errors(self):
        import httpx
        client=AsyncMock();client._token='fixture'
        response=httpx.Response(200,text='{"assemblyCharts":[],"preparedCharts":[{"amount":0.00000000123456789}]}')
        client._raw_request.return_value=response
        result=await read_charts(client,'getTree',product_id=uuid4(),department_id=uuid4(),at=date(2026,10,9))
        self.assertEqual(result['preparedCharts'][0]['amount'],Decimal('0.00000000123456789'))
        self.assertEqual(frozen_json(result)['preparedCharts'][0]['amount'],'0.00000000123456789')
        client._raw_request.side_effect=[httpx.Response(401),response]
        await read_charts(client,'getPrepared',product_id=uuid4(),department_id=uuid4(),at=date(2026,10,9))
        client._raw_request.side_effect=None;client._raw_request.return_value=httpx.Response(200,text='[]')
        with self.assertRaisesRegex(Exception,'RECIPE_ENVELOPE_INVALID'):
            await read_charts(client,'getTree',product_id=uuid4(),department_id=uuid4(),at=date(2026,10,9))
