"""K3 reviewed import, missing/zero prices, boundary and K2 preservation."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4
import unittest
from unittest.mock import patch

from sqlalchemy import select, func
from pydantic import ValidationError
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgePrice as Price
from app.models.audit import AuditEvent
from app.models.user import User
from app.models.employee import EmployeeRole, EmployeeRoleAssignment
from app.core.action_context import ActionContextError
from app.product_knowledge.prices import PriceSnapshot, price_preview, import_prices
from app.product_knowledge.management import LOCAL_FIELDS
from app.product_knowledge.bootstrap import PublicationError
from tests import test_product_knowledge as k1


class ProductPriceTests(unittest.TestCase):
    row = k1.ProductKnowledgeTests.row
    ingest = k1.ProductKnowledgeTests.ingest
    plan = k1.ProductKnowledgeTests.plan
    load = k1.ProductKnowledgeTests.load
    tearDown = k1.ProductKnowledgeTests.tearDown

    def setUp(self):
        k1.ProductKnowledgeTests.setUp(self)
        self.load()
        self.snapshot_prices = PriceSnapshot(source_id=self.source_id,
            observed_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
            confirmed_point_ids=[self.department_id], office_evidence='Office comparison fixture',
            prices=[dict(iiko_product_id=self.product, department_id=self.department_id,
                valid_from='2026-10-09', valid_to='2026-10-12', amount='0', currency='RUB',
                price_unit='шт', evidence='Office zero amount, unit and currency fixture')])

    def review(self, snapshot=None):
        with self.sessions() as db:
            return price_preview(db, db.get(User, 1), self.source_id, snapshot or self.snapshot_prices)

    def apply(self, snapshot=None, expected_hash=None):
        snapshot = snapshot or self.snapshot_prices
        expected_hash = expected_hash or self.review(snapshot)['plan_hash']
        with self.sessions.begin() as db:
            return import_prices(db, db.get(User, 1), self.source_id, snapshot, expected_hash=expected_hash)

    def test_zero_boundaries_retry_and_k2_preserved(self):
        with self.sessions.begin() as db:
            p = db.scalar(select(Product).where(Product.iiko_product_id == self.product))
            p.local_name = 'Ручное имя'; p.local_description = 'Ручное описание'; p.sale_status = 'OFF_SALE'
            p.version = 7; p.verified_at = datetime(2026, 10, 8, tzinfo=timezone.utc)
            p.verified_by_name = 'Управляющий'; p.composition = 'Состав EOS'
            pid = p.id
        with self.sessions() as db:
            before = {k: getattr(db.get(Product, pid), k) for k in LOCAL_FIELDS}
        reviewed_hash = self.review()['plan_hash']
        self.assertEqual(self.apply(expected_hash=reviewed_hash), dict(inserted=1, retained=0))
        self.assertEqual(self.apply(expected_hash=reviewed_hash), dict(inserted=0, retained=1))
        with self.sessions() as db:
            self.assertEqual(before, {k: getattr(db.get(Product, pid), k) for k in LOCAL_FIELDS})
            self.assertEqual(db.scalar(select(func.count()).select_from(Price)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.event_type == 'PRODUCT_KNOWLEDGE_PRICE_CONFIRMED')), 1)
        for day, present in [('2026-10-08', False), ('2026-10-09', True), ('2026-10-11', True), ('2026-10-12', False)]:
            result = self.client.get(f'/products/{pid}?department_id={self.department_id}&price_at={day}').json()
            self.assertEqual(result['price'] is not None, present)
            if present:
                self.assertEqual(float(result['price']['amount']), 0)

    def test_overlap_atomicity_unit_currency_and_hash(self):
        bad = self.snapshot_prices.model_copy(deep=True)
        bad.prices.append(bad.prices[0].model_copy(update={'valid_from': date(2026, 10, 10)}))
        with self.assertRaisesRegex(PublicationError, 'INTERVAL_CONFLICT'): self.review(bad)
        with self.assertRaisesRegex(PublicationError, 'REVIEW_REQUIRED'): self.apply(expected_hash='bad')
        bad = self.snapshot_prices.model_copy(deep=True); bad.prices[0].price_unit = 'кг'
        with self.assertRaisesRegex(PublicationError, 'UNIT_MISMATCH'): self.review(bad)
        self.apply()
        bad = self.snapshot_prices.model_copy(deep=True); bad.prices[0].currency = 'EUR'
        with self.assertRaisesRegex(PublicationError, 'INTERVAL_CONFLICT'): self.apply(bad)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Price)), 1)

    def test_points_source_and_unknown_uuid_fail_closed(self):
        bad = self.snapshot_prices.model_copy(deep=True); bad.source_id = 'unknown'
        with self.assertRaisesRegex(PublicationError, 'SOURCE_MISMATCH'): self.review(bad)
        bad = self.snapshot_prices.model_copy(deep=True); bad.prices[0].iiko_product_id = uuid4()
        with self.assertRaisesRegex(PublicationError, 'PRODUCT_MISSING'): self.review(bad)
        bad = self.snapshot_prices.model_copy(deep=True)
        bad.confirmed_point_ids = [uuid4()]; bad.prices[0].department_id = bad.confirmed_point_ids[0]
        with self.assertRaisesRegex(PublicationError, 'UNCONFIRMED_POINT'): self.review(bad)
        data = self.snapshot_prices.model_dump(); data['office_evidence'] = ' '
        with self.assertRaises(ValidationError): PriceSnapshot.model_validate(data)
        data = self.snapshot_prices.model_dump(); data['observed_at'] = datetime(2026, 10, 9)
        with self.assertRaises(ValidationError): PriceSnapshot.model_validate(data)

    def test_future_and_legacy_overlap_or_wrong_unit_hidden(self):
        self.apply()
        with self.sessions.begin() as db:
            p = db.scalar(select(Price)); pid = p.product_id
            db.add(Price(tenant_id='eclair', product_id=pid, department_id=self.department_id,
                valid_from=date(2026, 10, 10), valid_to=date(2026, 10, 11), amount=120,
                currency='RUB', price_unit='шт', evidence='conflicting legacy fixture',
                verified_by_user_id=1, observed_at=self.snapshot_prices.observed_at))
        result = self.client.get(f'/products/{pid}?department_id={self.department_id}&price_at=2026-10-10').json()
        self.assertIsNone(result['price'])
        self.assertEqual(result['price_conflict_points'], [str(self.department_id)])
        with self.sessions.begin() as db:
            for p in db.scalars(select(Price)): p.price_unit = 'кг'
        result = self.client.get(f'/products/{pid}?department_id={self.department_id}&price_at=2026-10-09').json()
        self.assertIsNone(result['price'])

    def test_audit_failure_rolls_back_entire_import(self):
        with patch('app.product_knowledge.prices.record_audit_event', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError): self.apply()
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Price)), 0)

    def test_non_admin_cannot_import_or_preview(self):
        reviewed_hash = self.review()['plan_hash']
        with self.sessions.begin() as db:
            for role in db.scalars(select(EmployeeRoleAssignment)): role.role = EmployeeRole.NETWORK_MANAGER
        with self.assertRaises(ActionContextError): self.review()
        with self.assertRaises(ActionContextError): self.apply(expected_hash=reviewed_hash)

    def test_changed_amount_invalidates_review_hash(self):
        reviewed_hash = self.review()['plan_hash']
        changed = self.snapshot_prices.model_copy(deep=True)
        changed.prices[0].amount = Decimal('140')
        with self.assertRaisesRegex(PublicationError, 'REVIEW_REQUIRED'):
            self.apply(changed, expected_hash=reviewed_hash)
