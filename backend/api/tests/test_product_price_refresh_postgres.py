"""Isolated PG verification for K3 source lock, immutable history and downgrade guard."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timezone
from sqlalchemy import select, func, inspect
from app.models.user import User
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgePriceSnapshot as Snapshot
from app.models.employee import IikoDepartmentMapping
from app.product_knowledge.price_refresh import SourcePriceSnapshot, source_price_preview, publish_source_prices
from tests import test_product_knowledge_postgres as pg
from tests.test_product_price_refresh import context


@unittest.skipUnless(os.getenv('PRODUCT_KNOWLEDGE_TEST_DATABASE_URL'), 'Dedicated PostgreSQL not configured')
class PriceRefreshPostgresTests(unittest.TestCase):
    setUp=pg.ProductKnowledgePostgresTests.setUp
    tearDown=pg.ProductKnowledgePostgresTests.tearDown
    load=pg.ProductKnowledgePostgresTests.load

    def test_concurrent_retry_snapshot_constraints_and_guard(self):
        self.load()
        with self.sessions() as db:
            products={str(p.iiko_product_id):dict(id=str(p.id),unit_id=str(p.unit_id),unit_name=p.unit_name) for p in db.scalars(select(Product).where(Product.tenant_id==self.tenant))}
            mapping=db.scalar(select(IikoDepartmentMapping).where(IikoDepartmentMapping.tenant_id==self.tenant))
            point=mapping.olap_department_id
        snapshot=SourcePriceSnapshot(source_id=self.source,confirmed_point_ids=[self.department],currency='RUB',office_evidence='Office fixture',
            observed_at=datetime.now(timezone.utc),date_from=date(2026,10,1),date_to=date(2026,11,1),
            products=products,point_links={str(self.department):str(point)},revisions={str(self.department):1},
            contexts=[context(next(iter(products)),point)])
        def store(_):
            with self.sessions.begin() as db:
                review=source_price_preview(db,self.tenant,snapshot)
                return publish_source_prices(db,self.tenant,snapshot,expected_hash=review['plan_hash'],actor=db.get(User,self.actor)).id
        with ThreadPoolExecutor(max_workers=2) as workers:ids=list(workers.map(store,range(2)))
        self.assertEqual(ids[0],ids[1])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.tenant_id==self.tenant)),1)
        self.assertIn('ck_pk_price_snapshot_dates',{c['name'] for c in inspect(self.engine).get_check_constraints('product_knowledge_price_snapshots')})

        from app.automation.schedules import create_schedule, InvalidAutomationScheduleActionError
        from app.schemas.automation import AutomationScheduleCreate
        from app.models.automation import AutomationSchedule
        from app.core.config import settings
        from unittest.mock import patch
        payload = AutomationScheduleCreate(name='Prices fixture', automation_type='products.sync_iiko_prices',
            scope_type='company', scope_id=None, schedule_config={'type':'interval','minutes':60},
            payload=snapshot.model_dump(mode='json',include={'source_id','confirmed_point_ids','currency','office_evidence'}),
            recipients=[],timezone='Asia/Yekaterinburg',is_enabled=False)
        def create(_):
            with self.sessions() as db:
                try:
                    return create_schedule(db,payload,created_by_user_id=self.actor).id
                except InvalidAutomationScheduleActionError as error:
                    return str(error)
        with patch.object(settings,'default_tenant_id',self.tenant):
            with ThreadPoolExecutor(max_workers=2) as workers: outcomes=list(workers.map(create,range(2)))
        self.assertEqual(sum(isinstance(value,int) for value in outcomes),1)
        self.assertTrue(any(isinstance(value,str) and 'уже существует' in value for value in outcomes))
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AutomationSchedule).where(AutomationSchedule.tenant_id==self.tenant)),1)

        from app.product_knowledge.service import price_health
        from app.models.supply import Department
        from alembic import command
        from alembic.config import Config
        from pathlib import Path
        from sqlalchemy import text
        with self.sessions() as db:
            health = price_health(db, db.get(User,self.actor), self.source, [db.get(Department,self.department)])[0]
            self.assertFalse(health['stale']); self.assertEqual(health['last_success_at'], snapshot.observed_at)
        with self.assertRaisesRegex(RuntimeError, 'PRODUCT_PRICE_SNAPSHOTS_EXIST'):
            command.downgrade(Config(str(Path(__file__).parents[1]/'alembic.ini')), '20261009_0075')
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text('select version_num from alembic_version')).scalar(), '20261009_0076')
