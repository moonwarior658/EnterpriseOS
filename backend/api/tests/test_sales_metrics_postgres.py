"""Run only on a disposable, migrated localhost sales database."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault('POSTGRES_DB', 'test')
os.environ.setdefault('POSTGRES_USER', 'test')
os.environ.setdefault('POSTGRES_PASSWORD', 'test')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret')

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, DBAPIError
from sqlalchemy.orm import sessionmaker
from app.models.audit import AuditEvent
from app.models.employee import Employee, EmployeeRole, EmployeeRoleAssignment
from app.models.sales import SalesTarget
from app.models.user import User
from app.sales.metrics import create_target, target_history
from app.schemas.sales import TargetCreate

URL = os.getenv('SALES_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'SALES_TEST_DATABASE_URL not configured')
class SalesMetricsPostgresTests(unittest.TestCase):
    def setUp(self):
        url = make_url(URL)
        self.assertEqual(url.database, 'eos_sales_foundation_test')
        self.assertIn(url.host, ('127.0.0.1', 'localhost'))
        self.engine = create_engine(URL)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.tenant = 'metrics-test-' + uuid4().hex[:16]
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as db:
            self.assertEqual(db.scalar(text('select version_num from alembic_version')), '20261006_0071')
            user = User(username=self.tenant, display_name='Test', hashed_password='test', tenant_id=self.tenant)
            db.add(user); db.flush()
            self.user_id = user.id
            employee = Employee(tenant_id=self.tenant, linked_user_id=user.id, full_name='Test',
                                birth_date=date(1990,1,1), phone='0', residence_address='Test')
            db.add(employee); db.flush()
            db.add(EmployeeRoleAssignment(tenant_id=self.tenant, employee_id=employee.id,
                role=EmployeeRole.DEPUTY_DIRECTOR, valid_from=now-timedelta(days=1), reason='test', assigned_by_user_id=user.id))
        with self.sessions.begin() as db:
            self.target = create_target(db, db.get(User,self.user_id),
                TargetCreate(metric='fullness',month=date(2026,10,1),value=Decimal('3.123456')))

    def tearDown(self):
        self.engine.dispose()

    def test_precision_immutability_and_constraints(self):
        with self.sessions() as db:
            self.assertEqual(db.get(SalesTarget,self.target.id).value, Decimal('3.123456'))
            self.assertEqual(db.scalar(select(AuditEvent.authorized_as).where(AuditEvent.entity_id==str(self.target.id))), 'DEPUTY_DIRECTOR')
        for sql in ['UPDATE sales_targets SET value=4 WHERE id=:id','DELETE FROM sales_targets WHERE id=:id']:
            with self.assertRaises(DBAPIError):
                with self.sessions.begin() as db: db.execute(text(sql),{'id':self.target.id})
        for changes in [dict(value=0),dict(value=Decimal('NaN')),dict(month=date(2026,10,2)),
                        dict(metric='bad'),dict(revision=0),dict(created_by_user_id=2147483647)]:
            with self.assertRaises(IntegrityError):
                with self.sessions.begin() as db:
                    fields={c.name:getattr(self.target,c.name) for c in SalesTarget.__table__.columns if c.name!='id'}
                    fields['revision']=10
                    fields.update(changes)
                    db.add(SalesTarget(**fields));db.flush()
        with self.sessions() as db:
            self.assertEqual(len(target_history(db,self.tenant)),1)

    def test_concurrent_correction_one_winner_and_atomic_audit(self):
        barrier = Barrier(2)
        def history(*args, **kwargs):
            result=target_history(*args,**kwargs)
            barrier.wait(timeout=10)
            return result
        def write(value):
            try:
                with self.sessions.begin() as db:
                    create_target(db,db.get(User,self.user_id),TargetCreate(metric='fullness',
                        month=date(2026,10,1),value=value,expected_revision=1))
                return 'success'
            except IntegrityError:
                return 'conflict'
        with patch('app.sales.metrics.target_history',side_effect=history):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results=list(executor.map(write,[Decimal('3.5'),Decimal('4')]))
        self.assertCountEqual(results,['success','conflict'])
        with self.sessions() as db:
            self.assertEqual([t.revision for t in target_history(db,self.tenant)],[1,2])
            self.assertEqual(len(db.scalars(select(AuditEvent).where(AuditEvent.tenant_id==self.tenant)).all()),2)
