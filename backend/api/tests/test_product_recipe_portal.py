"""K5D authorization, safe projection, exact version approvals and Core commands."""
import copy
import unittest
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select, func, MetaData, JSON, Integer, BigInteger, event
from sqlalchemy.dialects.postgresql import JSONB
from fastapi import HTTPException
from app.models.automation import OutboxEvent, AutomationExecution, ExecutionStatus
from app.models.employee import EmployeeRole, EmployeeRoleAssignment
from app.models.audit import AuditEvent
from app.models.user import User, UserAccountType
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from app.models.product_recipe import ProductRecipeObservation as Observation
from app.product_knowledge import recipe_portal as portal
from tests import test_product_recipes as k5b


class RecipePortalTests(unittest.TestCase):
    row = k5b.RecipePersistenceTests.row
    ingest = k5b.RecipePersistenceTests.ingest
    plan = k5b.RecipePersistenceTests.plan
    load = k5b.RecipePersistenceTests.load
    apply = k5b.RecipePersistenceTests.apply
    tearDown = k5b.RecipePersistenceTests.tearDown

    def setUp(self):
        k5b.RecipePersistenceTests.setUp(self)
        metadata = MetaData()
        AutomationExecution.__table__.to_metadata(metadata)
        table = OutboxEvent.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON(); column.server_default = None
            if column.primary_key and isinstance(column.type, BigInteger):
                column.type = Integer()
        table.create(self.engine)
        # SQLite must use a real outer transaction before SAVEPOINTs so that
        # injected post-enqueue failures exercise the same rollback as PostgreSQL.
        with self.engine.connect() as connection:
            connection.connection.driver_connection.isolation_level = None
        event.listen(self.engine, 'begin', lambda connection: connection.exec_driver_sql('BEGIN'))
        self.apply()
        with self.sessions() as db:
            observation = db.scalar(select(Observation))
            self.local = observation.product_id
            self.observation_id = observation.id
            self.manifest = observation.payload['manifest_hash']
            self.context = portal.context_key(observation.payload)
        self.path = f'/products/{self.local}/recipes'

    def role(self, role):
        with self.sessions.begin() as db:
            assignment = db.scalar(select(EmployeeRoleAssignment).where(EmployeeRoleAssignment.employee_id == self.admin_employee_id))
            assignment.role = role
            from app.models.supply import Department, DepartmentBusinessType
            db.get(Department,self.department_id).business_type = DepartmentBusinessType.PRODUCTION if role in {EmployeeRole.HEAD_OF_PRODUCTION,EmployeeRole.CHEF_CONFECTIONER} else DepartmentBusinessType.RETAIL_POINT

    def confirmation(self):
        return dict(observation_id=str(self.observation_id), manifest_hash=self.manifest,
                    office_evidence='Сверено с iikoOffice: нормы и вложенные версии совпадают')

    def refresh_body(self):
        return dict(context_key=self.context, effective_on='2026-10-09', request_id=str(uuid4()))

    def test_roles_protect_all_recipe_paths_and_technology(self):
        for role in EmployeeRole:
            with self.subTest(role=role):
                self.role(role)
                expected = 200 if role in {EmployeeRole.ADMIN, EmployeeRole.HEAD_OF_PRODUCTION, EmployeeRole.CHEF_CONFECTIONER} else 403
                response = self.client.get(self.path)
                self.assertEqual(response.status_code, expected)
                if expected == 403:
                    self.assertNotIn('Source text', response.text)
                    self.assertEqual(self.client.post(self.path+'/confirm', json=self.confirmation()).status_code, 403)
                    self.assertEqual(self.client.post(self.path+'/refresh', json=self.refresh_body()).status_code, 403)
                else:
                    self.assertIn('Source text', response.text)
        self.role(EmployeeRole.DIRECTOR)
        response=self.client.get(f'/products/{self.local}');self.assertFalse(response.json()['recipe_access'])
        self.assertNotIn('technology', response.text)
        self.assertNotIn('manifest_hash', response.text)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AutomationExecution)), 0)

    def test_exact_decimals_source_prepared_history_and_no_raw_internals(self):
        # Import unknown source fields into a referenced version, not an orphan.
        self.collected['bundles'][str(self.product)]['tree']['assemblyCharts'][0]['price']='secret cost'
        self.collected['observed_at']+=timedelta(seconds=1)
        self.apply(uuid4())
        response=self.client.get(self.path)
        self.assertEqual(response.headers['cache-control'],'no-store')
        data=response.json();obs=data['observation']
        self.assertEqual(obs['status_label'],'Требует проверки');self.assertFalse(obs['ready_for_production'])
        source=next(c for c in obs['charts'] if 'ASSEMBLED' in c['roles'])
        self.assertEqual(source['items'][0]['gross'],'0.00000000123456789')
        self.assertEqual(source['base_amount'],'1');self.assertEqual(source['unit'],'шт')
        self.assertTrue(any('TREE' in c['roles'] and c['product_id'] != obs['root_product_id'] for c in obs['charts']))
        prepared=next(c for c in obs['charts'] if c['kind']=='PREPARED')
        self.assertIsNone(prepared['items'][0]['gross']);self.assertEqual(prepared['items'][0]['writeoff'],'0.00000000123456789')
        self.assertIn('Производственный склад не подтверждён',obs['issues'])
        for forbidden in ('source_responses','execution_id','scope_evidence','raw_payload','secret cost','content_hash'):
            self.assertNotIn(forbidden,response.text)
        self.assertEqual(data['total'],2)

    def test_confirmation_is_immutable_idempotent_and_exact_observation(self):
        with self.sessions() as db:
            original=copy.deepcopy(db.get(Observation,self.observation_id).payload)
            product_version=db.get(Product,self.local).version
        for _ in range(2):
            response=self.client.post(self.path+'/confirm',json=self.confirmation());self.assertEqual(response.status_code,200)
        obs=response.json()['observation'];self.assertIsNotNone(obs['confirmation'])
        self.assertEqual(obs['confirmation']['author'],'Администратор')
        self.assertTrue(obs['confirmation']['version_ids']);self.assertFalse(obs['ready_for_production'])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type=='PRODUCT_RECIPE_CONFIRMED')),1)
            self.assertEqual(db.get(Observation,self.observation_id).payload,original)
            self.assertEqual(db.get(Product,self.local).version,product_version)
        self.collected['observed_at'] += timedelta(seconds=1)
        self.apply(uuid4())
        latest=self.client.get(self.path).json()['observation'];self.assertIsNone(latest['confirmation'])
        self.assertEqual(self.client.post(self.path+'/confirm',json=self.confirmation()).status_code,409)
        historic=self.client.get(self.path,params={'observation_id':str(self.observation_id)}).json()
        self.assertFalse(historic['observation']['is_current']);self.assertIsNotNone(historic['observation']['confirmation'])

    def test_incomplete_conflict_hash_and_other_product_block_confirmation(self):
        wrong=self.confirmation();wrong['manifest_hash']='0'*64
        self.assertEqual(self.client.post(self.path+'/confirm',json=wrong).status_code,409)
        wrong['observation_id']=str(uuid4());self.assertEqual(self.client.post(self.path+'/confirm',json=wrong).status_code,404)
        with self.sessions() as db:second=db.scalar(select(Product).where(Product.iiko_product_id==self.second)).id
        self.assertEqual(self.client.get(f'/products/{second}/recipes',params={'observation_id':str(self.observation_id)}).status_code,404)
        bundle=self.collected['bundles'][str(self.product)]
        bundle['tree']['assemblyCharts'][0]['productSizeAssemblyStrategy']='SPECIFIC'
        self.collected['observed_at']+=timedelta(seconds=1);self.apply(uuid4())
        data=self.client.get(self.path).json();obs=data['observation'];self.assertEqual(obs['status'],'INCOMPLETE')
        self.assertNotIn('CONFIRM',data['allowed_actions'])
        command=dict(observation_id=obs['id'],manifest_hash=obs['manifest_hash'],office_evidence='Office incomplete')
        self.assertEqual(self.client.post(self.path+'/confirm',json=command).status_code,409)
        bundle['tree']['assemblyCharts'][0]['items'][0]['productId']=str(self.product)
        self.collected['observed_at']+=timedelta(seconds=1);self.apply(uuid4())
        obs=self.client.get(self.path).json()['observation'];self.assertEqual(obs['status'],'CONFLICT')
        command.update(observation_id=obs['id'],manifest_hash=obs['manifest_hash'])
        self.assertEqual(self.client.post(self.path+'/confirm',json=command).status_code,409)

    def test_manual_refresh_retries_single_outbox_safe_progress_and_terminal(self):
        self.role(EmployeeRole.CHEF_CONFECTIONER)
        command=self.refresh_body()
        with patch('app.integrations.iiko.client.IikoServerClient.get_recipe_charts',side_effect=AssertionError('request path I/O')):
            for body in (command,command,self.refresh_body()):
                response=self.client.post(self.path+'/refresh',json=body);self.assertEqual(response.status_code,202)
                self.assertEqual(response.json()['refresh']['state'],'pending')
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AutomationExecution)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(OutboxEvent)),1)
            execution=db.scalar(select(AutomationExecution));self.assertEqual(execution.payload['product_ids'],[str(self.product)])
            self.assertIsNone(execution.schedule_id);self.assertIsNone(execution.payload['warehouse_id'])
        self.assertEqual(self.client.post(self.path+'/confirm',json=self.confirmation()).status_code,409)
        changed={**command,'effective_on':'2026-05-31'}
        self.assertEqual(self.client.post(self.path+'/refresh',json=changed).status_code,409)
        with self.sessions.begin() as db:
            execution=db.scalar(select(AutomationExecution));execution.status=ExecutionStatus.FAILED
            execution.error_message='private stack';execution.result={'raw_payload':'private payload'}
        response=self.client.get(self.path);self.assertIn('Не удалось обновить',response.text)
        self.assertNotIn('private',response.text);self.assertFalse(response.json()['refresh']['active'])
        # Lost response retry returns the old terminal execution, never launches another.
        self.assertEqual(self.client.post(self.path+'/refresh',json=command).json()['refresh']['state'],'failed')
        self.assertEqual(self.client.post(self.path+'/refresh',json=self.refresh_body()).status_code,202)
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(AutomationExecution)),2)

    def test_unknown_context_tenant_service_actor_and_transaction_rollback(self):
        command=self.refresh_body();command['context_key']='0'*64
        self.assertEqual(self.client.post(self.path+'/refresh',json=command).status_code,409)
        with patch('app.product_knowledge.recipe_portal.record_audit_event',side_effect=RuntimeError('fixture')):
            with self.assertRaisesRegex(RuntimeError,'fixture'):
                self.client.post(self.path+'/refresh',json=self.refresh_body())
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(AutomationExecution)),0)
        with self.sessions() as db:
            actor=db.get(User,1);actor.tenant_id='foreign'
            with patch('app.product_knowledge.recipe_portal.authorize'):
                with self.assertRaises(HTTPException) as error:portal.detail(db,actor,self.local)
                self.assertEqual(error.exception.status_code,404)
        with self.sessions.begin() as db:db.get(User,1).account_type=UserAccountType.SERVICE
        self.assertEqual(self.client.get(self.path).status_code,403)

    def test_history_paging_and_first_load_of_existing_product_only(self):
        for i in range(3):
            self.collected['observed_at']+=timedelta(seconds=1);self.apply(uuid4())
        data=self.client.get(self.path,params={'offset':2,'limit':1}).json()
        self.assertEqual(data['total'],4);self.assertEqual(len(data['history']),1)
        with self.sessions() as db:second=db.scalar(select(Product).where(Product.iiko_product_id==self.second)).id
        path=f'/products/{second}/recipes'
        data=self.client.get(path).json();self.assertIsNone(data['observation']);self.assertIn('REFRESH',data['allowed_actions'])
        self.assertEqual(self.client.post(path+'/refresh',json=self.refresh_body()).status_code,202)
        self.assertEqual(self.client.get(self.path,params={'context_key':'0'*64}).status_code,404)
        self.assertEqual(self.client.get(self.path,params={'limit':101}).status_code,422)
        with self.sessions() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Product)),2)


class RecipeNormTests(unittest.TestCase):
    def test_exact_zero_missing_and_invalid_values(self):
        for source,expected in [(0,'0'),('0.000000000000123456789','0.000000000000123456789'),(None,None),('NaN',None),('-1',None),(True,None)]:
            self.assertEqual(portal.numeric(source),expected)
