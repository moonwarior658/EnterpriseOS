"""A5 immutable DB boundary and serialized concurrent finalization on disposable PG."""
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError, IntegrityError
from app.models.sales import SalesSyncState, SalesDaySync, SalesPeriodSnapshot
from app.sales.reports import capture
from app.sales.metrics import period
from app.schemas.sales import PeriodKind

URL = os.getenv('SALES_REPORTS_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'SALES_REPORTS_TEST_DATABASE_URL not configured')
class SalesReportsPostgresTests(unittest.TestCase):
    def setUp(self):
        url = make_url(URL)
        self.assertEqual(url.database, 'eos_sales_foundation_test')
        self.assertIn(url.host, ('127.0.0.1', 'localhost'))
        self.engine = create_engine(URL)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.tenant = 'reports-'+uuid4().hex[:16]; self.source = uuid4().hex*2
        self.now = datetime(2026,10,6,10,tzinfo=timezone.utc)
        self.selected = period(PeriodKind.WEEK, anchor=date(2026,9,28), today=self.now.date())
        with self.sessions.begin() as db:
            self.assertEqual(db.scalar(text('select version_num from alembic_version')), '20261006_0073')
            db.add(SalesSyncState(tenant_id=self.tenant, source_id=self.source, source_timezone='Asia/Yekaterinburg', history_from=date(2026,9,21), backfill_next=date(2026,9,21)))
            db.flush()
            day = self.selected.previous_start
            while day <= self.selected.end:
                db.add(SalesDaySync(tenant_id=self.tenant, source_id=self.source, business_date=day,last_success_at=self.now,row_count=0))
                day += timedelta(days=1)

    def tearDown(self):
        self.engine.dispose()

    def test_concurrent_one_final_and_sql_immutability(self):
        def write():
            with self.sessions.begin() as db:
                state = db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id==self.tenant).with_for_update())
                row, reason = capture(db, state, self.selected, now=self.now)
                self.assertIsNone(reason)
                return row.id
        with patch('app.sales.metrics.source_today',return_value=self.now.date()):
            with ThreadPoolExecutor(max_workers=2) as executor: ids = list(executor.map(lambda _: write(),range(2)))
        self.assertEqual(ids[0],ids[1])
        for sql in ['UPDATE sales_period_snapshots SET payload=\'{}\' WHERE id=:id','DELETE FROM sales_period_snapshots WHERE id=:id']:
            with self.assertRaises(DBAPIError):
                with self.sessions.begin() as db: db.execute(text(sql),{'id':ids[0]})
        with self.assertRaises(IntegrityError):
            with self.sessions.begin() as db:
                original = db.get(SalesPeriodSnapshot,ids[0])
                fields = {c.name:getattr(original,c.name) for c in SalesPeriodSnapshot.__table__.columns if c.name!='id'}
                db.add(SalesPeriodSnapshot(**fields));db.flush()
