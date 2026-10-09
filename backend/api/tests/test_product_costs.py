"""SSN calculation/RBAC/history checks; distinguishes independent Office evidence."""
import copy
import json
import os
from pathlib import Path
os.environ.setdefault('POSTGRES_DB','test');os.environ.setdefault('POSTGRES_USER','test')
os.environ.setdefault('POSTGRES_PASSWORD','test');os.environ.setdefault('JWT_SECRET_KEY','test-jwt-secret')
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from unittest.mock import patch
from sqlalchemy import select, func
from app.models.product_cost import ProductCostObservation as Observation, ProductCostVerification as Verification
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from app.models.user import User
from app.models.employee import EmployeeRole, EmployeeRoleAssignment
from app.product_knowledge.cost_calculation import calculate, number
from app.product_knowledge.costs import CostRefreshPayload, publish_costs, scope
from app.product_knowledge.cost_portal import CostConfirmation, confirm, cost_rows, detail
from app.schemas.automation import validate_automation_action_payload, validate_automation_schedule_contract, IntervalScheduleConfig
from tests import test_product_knowledge as k1


def fixture(root=None, unit=None):
    root, child, goods, unit = root or str(uuid4()),str(uuid4()),str(uuid4()),unit or str(uuid4())
    def chart(pid,ingredient,norm,basis):
        return dict(key=str(uuid4()),root_key=pid,assembledAmount=basis,dateFrom='2026-01-01',dateTo=None,
            direct_spec=dict(departments=[],inverse=False),size_strategy='COMMON',
            items=[dict(product_key=ingredient,amountIn=norm,storeSpecification=None,size_specified=False)])
    return dict(key=root,charts=[chart(root,child,'0.5','1'),chart(child,goods,'0.3','2')],
        references=[dict(key=p,name='Same name',type=t,mainUnit_key=unit,unitWeight='1',deleted=False)
            for p,t in [(root,'DISH'),(child,'PREPARED'),(goods,'GOODS')]],
        units=[dict(key=unit,name='кг')],balances=[dict(rows=[dict(product_key=goods,store_key=str(uuid4()),amount='3',sum='10')])])


class CostCalculationTests(unittest.TestCase):
    def test_nested_norms_per_output_basis_and_precise_rounding(self):
        result=calculate(fixture(),at=date(2026,10,9));self.assertEqual(result['amount'],'0.25')
        self.assertEqual(result['components'][0]['quantity'],'0.075');self.assertEqual(result['components'][0]['unit_cost'],'3.33')
        self.assertEqual(result['components'][0]['contribution'],'0.24975')
    def test_positive_pool_negative_only_and_source_zero(self):
        r=fixture();row=r['balances'][0]['rows'][0];r['balances'][0]['rows'].append(dict(row,store_key=str(uuid4()),amount='-99',sum='-9900'))
        self.assertEqual(calculate(r,at=date(2026,10,9))['amount'],'0.25')
        r['balances'][0]['rows']=[dict(row,amount='-3',sum='-10')]
        self.assertIn('NEGATIVE_STOCK_RATIO',calculate(r,at=date(2026,10,9))['risks'])
        r['balances'][0]['rows'][0]['sum']='0';result=calculate(r,at=date(2026,10,9))
        self.assertEqual(result['amount'],'0.00');self.assertIn('ZERO_VALUATION_REQUIRES_REVIEW',result['risks'])
        r['balances'][0]['rows']=[];self.assertIsNone(calculate(r,at=date(2026,10,9))['amount'])
    def test_direct_compound_uses_stock_not_its_raw_set(self):
        r=fixture();child=r['charts'][1]['root_key'];r['charts'][1]['direct_spec']['inverse']=True
        r['balances'][0]['rows'].append(dict(product_key=child,store_key=str(uuid4()),amount='1',sum='100'))
        self.assertEqual(calculate(r,at=date(2026,10,9))['amount'],'50.00')
        r['charts'][1]['direct_spec']['departments']=['special'];self.assertIsNone(calculate(r,at=date(2026,10,9))['amount'])
        self.assertEqual(calculate(r,at=date(2026,10,9),department='other')['amount'],'50.00')
        self.assertEqual(calculate(r,at=date(2026,10,9),department='special')['amount'],'0.25')
    def test_invalid_shapes_cycles_duplicates_units_size_and_numbers(self):
        for mutate in (lambda r:r['charts'].append(copy.deepcopy(r['charts'][0])),lambda r:r['charts'][1]['items'][0].update(product_key=r['key']),
            lambda r:r.update(units=[]),lambda r:r['charts'][1].update(direct_spec=None),lambda r:r['charts'][0].update(size_strategy='SPECIFIC'),
            lambda r:r['balances'][0]['rows'].append(copy.deepcopy(r['balances'][0]['rows'][0])),lambda r:r['charts'][0]['items'][0].update(amountIn='NaN')):
            r=fixture();mutate(r);self.assertIsNone(calculate(r,at=date(2026,10,9))['amount'])
        for bad in (False,1.2,'NaN','Infinity',None):
            with self.assertRaises(ValueError):number(bad)
    def test_specific_without_assigned_scale_is_not_a_size_selection(self):
        r=fixture();r['charts'][0]['size_strategy']='SPECIFIC'
        self.assertIsNone(calculate(r,at=date(2026,10,9))['amount'])
        r['charts'][0]['scale_absent']=True
        self.assertEqual(calculate(r,at=date(2026,10,9))['amount'],'0.25')
        r['charts'][0]['items'][0]['size_specified']=True
        self.assertIsNone(calculate(r,at=date(2026,10,9))['amount'])

    def test_mass_office_strict_and_separate_diagnostic_branches(self):
        source=json.loads((Path(__file__).parents[3]/'docs/evidence/STAGE_3_2_K5C_MASS_2026-10-09.json').read_text())
        exact=0;unresolved=[]
        for r in source['roots']:
            refs={p['key']:p for p in r['references']};self.assertEqual(refs[r['key']]['num'],r['office']['article']);self.assertEqual(refs[r['key']]['code'],r['office']['code'])
            actual=calculate(r,at=date(2026,10,9))
            if actual['amount'] is not None:self.assertEqual(actual['amount'],r['office']['ssn']);exact+=1
            else:unresolved.append(r['office']['article'])
            # A what-if check cannot approve either its size or department setting.
            diagnostic=copy.deepcopy(r)
            for c in diagnostic['charts']:c['size_strategy']='COMMON'
            conditional=calculate(diagnostic,at=date(2026,10,9),department='OFFICE_CONTEXT_OUTSIDE_EXCEPTION')
            self.assertEqual(conditional['amount'],r['office']['ssn'])
        self.assertEqual(exact,47);self.assertEqual(set(unresolved),{'76243','76242'});self.assertEqual(len(source['roots']),49)


class CostPersistenceTests(unittest.TestCase):
    row=k1.ProductKnowledgeTests.row;ingest=k1.ProductKnowledgeTests.ingest;plan=k1.ProductKnowledgeTests.plan;load=k1.ProductKnowledgeTests.load;tearDown=k1.ProductKnowledgeTests.tearDown
    def setUp(self):
        k1.ProductKnowledgeTests.setUp(self);self.load();self.execution=uuid4();self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.policy=CostRefreshPayload(source_id=self.source_id,product_ids=[self.product],warehouse_ids=[],context_label='Explicit Office aggregate',scope_evidence='Fixture confirmed source warehouse aggregation')
        with self.sessions() as db:
            products=scope(db,'eclair',self.policy);p=db.get(Product,UUID(products[str(self.product)]));self.local=p.id;self.root=fixture(str(self.product),str(p.unit_id))
        self.snapshot=dict(products=products,roots={str(self.product):self.root},scope=self.policy.model_dump(mode='json'),stock_at=self.now,observed_at=self.now)
    def apply(self,execution=None):
        with self.sessions.begin() as db:return publish_costs(db,'eclair',self.snapshot,execution_id=execution or self.execution)
    def command(self,db,**kw):
        row=db.scalar(select(Observation).where(Observation.product_id==self.local).order_by(Observation.observed_at.desc()))
        return CostConfirmation(observation_id=row.id,content_hash=row.content_hash,office_ssn='0.25',estimated=False,warehouse_confirmed=True,context_confirmed=True,office_evidence='Synthetic independent Office agreement and explicit scope',**kw)
    def test_idempotent_history_unknown_money_hidden_and_no_adjacent_mutation(self):
        first=self.apply();self.assertEqual(first,self.apply())
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Observation)),1);result=detail(db,db.get(User,1),self.local,now=self.now)
            self.assertIsNone(result['current']['amount']);self.assertEqual(result['current']['components'],[]);before=[p.provenance for p in db.scalars(select(Product))]
        self.apply(uuid4())
        with self.sessions() as db:self.assertEqual(before,[p.provenance for p in db.scalars(select(Product))])
    def test_confirmation_exact_amount_context_hash_and_staleness(self):
        self.apply()
        from fastapi import HTTPException
        with self.sessions.begin() as db:
            actor=db.get(User,1);command=self.command(db)
            with self.assertRaises(HTTPException):confirm(db,actor,self.local,command.model_copy(update={'office_ssn':Decimal('0.26')}),now=self.now)
            with self.assertRaises(HTTPException):confirm(db,actor,self.local,command.model_copy(update={'content_hash':'f'*64}),now=self.now)
            confirm(db,actor,self.local,command,now=self.now);confirm(db,actor,self.local,command,now=self.now)
            result=detail(db,actor,self.local,now=self.now);self.assertEqual(result['current']['amount'],'0.25');self.assertEqual(result['current']['verification_author'],actor.display_name);self.assertEqual(len(result['current']['components']),1)
            self.assertIsNone(detail(db,actor,self.local,now=self.now+timedelta(hours=3))['current']['amount']);self.assertEqual(db.scalar(select(func.count()).select_from(Verification)),1)
    def test_auto_refresh_does_not_inherit_unobserved_office_estimation_status(self):
        self.apply()
        with self.sessions.begin() as db:confirm(db,db.get(User,1),self.local,self.command(db,allow_updates=True),now=self.now)
        self.snapshot['stock_at']=self.snapshot['observed_at']=self.now+timedelta(minutes=1);self.root['balances'][0]['rows'][0]['sum']='12';self.apply(uuid4())
        with self.sessions() as db:self.assertIsNone(detail(db,db.get(User,1),self.local,now=self.now+timedelta(minutes=2))['current']['amount'])
        self.root['charts'][0]['items'][0]['amountIn']='0.6';self.snapshot['stock_at']=self.snapshot['observed_at']=self.now+timedelta(minutes=3);self.apply(uuid4())
        with self.sessions() as db:self.assertIsNone(detail(db,db.get(User,1),self.local,now=self.now+timedelta(minutes=4))['current']['amount'])
    def test_estimated_and_zero_flag_never_inherited_without_new_office_evidence(self):
        self.root['balances'][0]['rows'][0]['sum']='0';self.apply()
        with self.sessions.begin() as db:
            row=db.scalar(select(Observation).where(Observation.product_id==self.local))
            command=CostConfirmation(observation_id=row.id,content_hash=row.content_hash,office_ssn='0',estimated=True,
                warehouse_confirmed=True,context_confirmed=True,allow_updates=True,office_evidence='Synthetic Office explicitly confirms zero estimated cost')
            confirm(db,db.get(User,1),self.local,command,now=self.now)
            self.assertEqual(detail(db,db.get(User,1),self.local,now=self.now)['current']['amount'],'0.00')
        self.snapshot['stock_at']=self.snapshot['observed_at']=self.now+timedelta(minutes=1);self.apply(uuid4())
        with self.sessions() as db:self.assertIsNone(detail(db,db.get(User,1),self.local,now=self.now+timedelta(minutes=2))['current']['amount'])

    def test_role_and_tenant_no_money(self):
        self.apply()
        for role in EmployeeRole:
            with self.sessions.begin() as db:db.scalar(select(EmployeeRoleAssignment).where(EmployeeRoleAssignment.employee_id == self.admin_employee_id)).role=role;db.get(User,1).is_admin=False
            with self.sessions() as db:
                allowed,values=cost_rows(db,db.get(User,1),[self.local])
                if role not in (EmployeeRole.ADMIN,EmployeeRole.HEAD_OF_PRODUCTION,EmployeeRole.CHEF_CONFECTIONER):self.assertFalse(allowed);self.assertEqual(values,{})
        with self.sessions() as db:
            actor=db.get(User,1);actor.tenant_id='foreign';self.assertEqual(cost_rows(db,actor,[self.local]),(False,{}))
    def test_responsible_production_roles_can_review_and_confirm_exact_snapshot(self):
        from app.models.supply import Department
        for index,role in enumerate((EmployeeRole.HEAD_OF_PRODUCTION,EmployeeRole.CHEF_CONFECTIONER)):
            with self.sessions.begin() as db:
                db.get(Department,self.department_id).business_type='PRODUCTION'
                db.scalar(select(EmployeeRoleAssignment).where(EmployeeRoleAssignment.employee_id==self.admin_employee_id)).role=role
                db.get(User,1).is_admin=False
            moment=self.now+timedelta(minutes=index)
            self.snapshot['stock_at']=self.snapshot['observed_at']=moment;self.apply(uuid4())
            with self.sessions.begin() as db:
                actor=db.get(User,1);self.assertTrue(detail(db,actor,self.local,now=moment,review=True)['review']['can_confirm'])
                confirm(db,actor,self.local,self.command(db),now=moment)
                self.assertEqual(detail(db,actor,self.local,now=moment)['current']['amount'],'0.25')

    def test_explicit_review_is_quarantined_and_confirmation_requires_warehouse(self):
        self.apply()
        from pydantic import ValidationError
        from fastapi import HTTPException
        with self.sessions() as db:
            actor=db.get(User,1)
            ordinary=detail(db,actor,self.local,now=self.now)
            self.assertIsNone(ordinary['review']);self.assertIsNone(ordinary['current']['amount'])
            preview=detail(db,actor,self.local,now=self.now,review=True)['review']
            self.assertEqual(preview['candidate_amount'],'0.25');self.assertEqual(len(preview['components']),1)
            self.assertTrue(preview['can_confirm']);self.assertEqual(preview['method'],'Расчёт EOS по ТТК')
            with self.assertRaises(ValidationError):CostConfirmation.model_validate(dict(self.command(db).model_dump(),warehouse_confirmed=False))
            self.assertIsNone(detail(db,actor,self.local,now=self.now+timedelta(hours=3),review=True)['review']['candidate_amount'])
        with self.sessions.begin() as db:confirm(db,db.get(User,1),self.local,self.command(db),now=self.now)
        from app.product_knowledge import cost_portal
        from hashlib import sha256
        source_key=sha256(str(self.product).encode()).hexdigest()[:16]
        exclusion=patch.object(cost_portal,'EXCLUDED_PRODUCT_KEYS',cost_portal.EXCLUDED_PRODUCT_KEYS | {source_key})
        exclusion.start();self.addCleanup(exclusion.stop)
        with self.sessions.begin() as db:db.get(Product,self.local).sku='renamed-article'
        with self.sessions.begin() as db:
            actor=db.get(User,1);preview=detail(db,actor,self.local,now=self.now,review=True)['review']
            self.assertEqual(preview['quality'],'EXCLUDED');self.assertFalse(preview['can_confirm'])
            self.assertIsNone(detail(db,actor,self.local,now=self.now)['current']['amount'])
            self.assertIsNone(cost_rows(db,actor,[self.local],now=self.now)[1][self.local]['amount'])
            with self.assertRaises(HTTPException) as failure:confirm(db,actor,self.local,self.command(db),now=self.now)
            self.assertEqual(failure.exception.status_code,409)
        self.root['balances'][0]['rows']=[];self.snapshot['stock_at']=self.snapshot['observed_at']=self.now+timedelta(minutes=1);self.apply(uuid4())
        with self.sessions() as db:
            preview=detail(db,db.get(User,1),self.local,now=self.now+timedelta(minutes=2),review=True)['review']
            self.assertIsNone(preview['candidate_amount']);self.assertEqual(preview['components'],[]);self.assertFalse(preview['can_confirm'])

    def test_api_safe_projection_permission_and_no_iiko(self):
        self.apply()
        with patch('app.integrations.iiko.client.IikoServerClient.authenticate',side_effect=AssertionError('No request I/O')):
            response=self.client.get(f'/products/{self.local}/costs');self.assertEqual(response.status_code,200);body=response.json();self.assertIsNone(body['current']['amount'])
            for private in ('stock_rows','execution_id','scope_evidence','unrounded_amount','signature'):self.assertNotIn(private,json.dumps(body))
        with self.sessions.begin() as db:db.scalar(select(EmployeeRoleAssignment).where(EmployeeRoleAssignment.employee_id == self.admin_employee_id)).role=EmployeeRole.SELLER;db.get(User,1).is_admin=False
        self.assertEqual(self.client.get(f'/products/{self.local}/costs').status_code,403)
        self.assertEqual(self.client.get(f'/products/{self.local}/costs?review=true').status_code,403)
    def test_reader_fixed_timestamp_scope_decimal_and_recipe_race(self):
        import asyncio
        from unittest.mock import AsyncMock
        from app.product_knowledge.costs import collect_costs
        pid=str(self.product);root=self.root
        def raw_chart(c):
            return dict(id=c['key'],assembledProductId=c['root_key'],assembledAmount=c['assembledAmount'],dateFrom=c['dateFrom'],dateTo=c['dateTo'],
                effectiveDirectWriteoffStoreSpecification=c['direct_spec'],productSizeAssemblyStrategy=c['size_strategy'],
                items=[dict(productId=i['product_key'],amountIn=i['amountIn'],storeSpecification=i['storeSpecification'],productSizeSpecification=None) for i in c['items']])
        tree=dict(assemblyCharts=[raw_chart(c) for c in root['charts']])
        refs=[dict(id=p['key'],mainUnit=p['mainUnit_key'],name=p['name'],type=p['type'],deleted=False) for p in root['references']]
        units=[dict(id=u['key'],name=u['name']) for u in root['units']]
        balances=[dict(product=b['product_key'],store=b['store_key'],amount=b['amount'],sum=b['sum']) for b in root['balances'][0]['rows']]
        calls=[];changed=False;tree_calls=0;scale_changed=False;scale_calls=0;scale_missing=False
        async def read(client,path,params):
            nonlocal tree_calls,scale_calls
            calls.append((path,params))
            if path.endswith('getTree'):
                tree_calls+=1
                if changed and tree_calls%2==0:return dict(tree,revision='changed')
                return copy.deepcopy(tree)
            if path.endswith('productScales'):
                scale_calls+=1
                return {} if scale_missing else {pid:dict(id='changed') if scale_changed and scale_calls%2==0 else None}
            if path.endswith('products/list'):return refs
            if path.endswith('balance/stores'):return balances
            return units
        class Client:
            async def __aenter__(self):return self
            async def __aexit__(self,*_):pass
        config=object()
        with patch('app.product_knowledge.costs.get_iiko_settings',return_value=config),patch('app.product_knowledge.costs.source_identity',return_value=self.source_id),patch('app.product_knowledge.costs.read_json',side_effect=read):
            result=asyncio.run(collect_costs(self.sessions,tenant_id='eclair',payload=self.policy,now=self.now,client_factory=lambda _:Client()))
            self.assertEqual(result['roots'][pid]['balances'][0]['rows'][0]['sum'],'10')
            stock_call=next(params for path,params in calls if path.endswith('balance/stores'))
            self.assertEqual([v for k,v in stock_call if k=='timestamp'],[self.now.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Yekaterinburg')).strftime('%Y-%m-%dT%H:%M:%S')])
            self.assertEqual(set(v for k,v in stock_call if k=='product'),set(p['key'] for p in root['references']))
            tree['assemblyCharts'][0]['productSizeAssemblyStrategy']='SPECIFIC'
            result=asyncio.run(collect_costs(self.sessions,tenant_id='eclair',payload=self.policy,now=self.now,client_factory=lambda _:Client()))
            self.assertTrue(result['roots'][pid]['charts'][0]['scale_absent'])
            self.assertEqual(calculate(result['roots'][pid],at=self.now.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Yekaterinburg')).date())['amount'],'0.25')
            scale_missing=True
            with self.assertRaisesRegex(ValueError,'COST_SCALES_INVALID'):asyncio.run(collect_costs(self.sessions,tenant_id='eclair',payload=self.policy,now=self.now,client_factory=lambda _:Client()))
            scale_missing=False;scale_changed=True;scale_calls=0
            with self.assertRaisesRegex(ValueError,'COST_SCALES_CHANGED'):asyncio.run(collect_costs(self.sessions,tenant_id='eclair',payload=self.policy,now=self.now,client_factory=lambda _:Client()))
            scale_changed=False;changed=True;tree_calls=0
            with self.assertRaisesRegex(ValueError,'COST_RECIPE_CHANGED'):asyncio.run(collect_costs(self.sessions,tenant_id='eclair',payload=self.policy,now=self.now,client_factory=lambda _:Client()))

    def test_schedule_requires_explicit_update_approval_and_unknown_latest_blocks_it(self):
        from app.product_knowledge.costs import require_verified_schedule
        self.apply()
        with self.sessions.begin() as db:
            with self.assertRaises(ValueError):require_verified_schedule(db,'eclair',self.policy)
            confirm(db,db.get(User,1),self.local,self.command(db,allow_updates=True),now=self.now)
            require_verified_schedule(db,'eclair',self.policy)
        self.root['balances'][0]['rows']=[];self.snapshot['stock_at']=self.snapshot['observed_at']=self.now+timedelta(minutes=1);self.apply(uuid4())
        with self.sessions() as db:
            self.assertIsNone(detail(db,db.get(User,1),self.local,now=self.now+timedelta(minutes=2))['current']['amount'])
            with self.assertRaises(ValueError):require_verified_schedule(db,'eclair',self.policy)

    def test_action_payload_and_hourly_contract(self):
        raw=self.policy.model_dump(mode='json');self.assertEqual(validate_automation_action_payload('products.sync_iiko_costs',raw),raw)
        config=IntervalScheduleConfig(type='interval',minutes=60);self.assertEqual(validate_automation_schedule_contract('products.sync_iiko_costs',config,raw),raw)
        with self.assertRaises(ValueError):validate_automation_schedule_contract('products.sync_iiko_costs',config.model_copy(update={'minutes':15}),raw)
