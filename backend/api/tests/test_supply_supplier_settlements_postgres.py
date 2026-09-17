import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.schemas.supplier_settlement import (
    SupplySupplierPaymentAllocationCreate,
    SupplySupplierSettlementAdjustmentCreate,
)
from app.supply.supplier_settlements import (
    SupplierSettlementValidationError,
    create_adjustment,
    create_allocation,
    reverse_allocation,
)


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplySupplierSettlementsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql") or url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Migration test accepts only local eos_supply_migration_test")
        cls.previous_settings = (settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port)
        settings.postgres_db, settings.postgres_user = url.database, url.username or ""
        settings.postgres_password, settings.postgres_host = url.password or "", url.host or ""
        settings.postgres_port = url.port or 5432
        cls.engine = create_engine(TEST_DATABASE_URL)
        if inspect(cls.engine).get_table_names():
            raise RuntimeError("Migration test database must be empty")
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port = cls.previous_settings

    def revision(self):
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_cycle_backfill_constraints_allocation_and_refund_concurrency(self):
        command.upgrade(self.config, "20260917_0052")
        supplier_id, request_id, order_id = uuid4(), uuid4(), uuid4()
        upd_request_id, upd_order_id = uuid4(), uuid4()
        delivery_request_id, delivery_order_id = uuid4(), uuid4()
        invoice_id, delivery_id = uuid4(), uuid4()
        upd_id, upd_delivery_id = uuid4(), uuid4()
        delivery_only_ids = [uuid4(), uuid4()]
        payment_30, payment_70 = uuid4(), uuid4()
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) VALUES (95301, 'settlement-pg-admin', 'Settlement Admin', 'x', 'settlement-pg', true, true)"))
            connection.execute(text("INSERT INTO supply_suppliers (id, tenant_id, display_name, is_active) VALUES (:id, 'settlement-pg', 'Settlement Supplier', true)"), {"id": supplier_id})
            connection.execute(text("INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) VALUES (:id, 'settlement-pg', 'ZR-SET-PG', CURRENT_DATE, 'READY', 95301)"), {"id": request_id})
            connection.execute(text("INSERT INTO supply_supplier_orders (id, tenant_id, number, supplier_id, purchase_request_id, status, total_amount, currency, created_by_user_id, confirmed_at, sent_at) VALUES (:id, 'settlement-pg', 'PO-SET-PG', :supplier, :request, 'SENT', 100, 'RUB', 95301, now(), now())"), {"id": order_id, "supplier": supplier_id, "request": request_id})
            for next_request, request_number, next_order, order_number in (
                (upd_request_id, "ZR-SET-UPD", upd_order_id, "PO-SET-UPD"),
                (delivery_request_id, "ZR-SET-DN", delivery_order_id, "PO-SET-DN"),
            ):
                connection.execute(text("INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) VALUES (:id, 'settlement-pg', :number, CURRENT_DATE, 'READY', 95301)"), {"id": next_request, "number": request_number})
                connection.execute(text("INSERT INTO supply_supplier_orders (id, tenant_id, number, supplier_id, purchase_request_id, status, total_amount, currency, created_by_user_id, confirmed_at, sent_at) VALUES (:id, 'settlement-pg', :number, :supplier, :request, 'SENT', 100, 'RUB', 95301, now(), now())"), {"id": next_order, "number": order_number, "supplier": supplier_id, "request": next_request})
            for document_id, kind, number in ((invoice_id, "INVOICE", "INV-PG"), (delivery_id, "DELIVERY_NOTE", "DN-PG")):
                connection.execute(text("INSERT INTO supply_supplier_documents (id, tenant_id, supplier_order_id, supplier_id, document_type, document_number, document_date, payment_due_date, status, supplier_display_name_snapshot, currency, total_amount, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'settlement-pg', :order, :supplier, :kind, :number, CURRENT_DATE, CURRENT_DATE - 1, 'RECORDED', 'Settlement Supplier', 'RUB', 100, 95301, now(), 95301)"), {"id": document_id, "order": order_id, "supplier": supplier_id, "kind": kind, "number": number})
            for document_id, kind, number in ((upd_id, "UPD", "UPD-PG"), (upd_delivery_id, "DELIVERY_NOTE", "DN-UPD-PG")):
                connection.execute(text("INSERT INTO supply_supplier_documents (id, tenant_id, supplier_order_id, supplier_id, document_type, document_number, document_date, status, supplier_display_name_snapshot, currency, total_amount, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'settlement-pg', :order, :supplier, :kind, :number, CURRENT_DATE, 'RECORDED', 'Settlement Supplier', 'RUB', 100, 95301, now(), 95301)"), {"id": document_id, "order": upd_order_id, "supplier": supplier_id, "kind": kind, "number": number})
            for index, document_id in enumerate(delivery_only_ids, start=1):
                connection.execute(text("INSERT INTO supply_supplier_documents (id, tenant_id, supplier_order_id, supplier_id, document_type, document_number, document_date, status, supplier_display_name_snapshot, currency, total_amount, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'settlement-pg', :order, :supplier, 'DELIVERY_NOTE', :number, CURRENT_DATE, 'RECORDED', 'Settlement Supplier', 'RUB', 100, 95301, now(), 95301)"), {"id": document_id, "order": delivery_order_id, "supplier": supplier_id, "number": f"DN-ONLY-{index}"})
            for payment_id, amount in ((payment_30, 30), (payment_70, 70)):
                connection.execute(text("INSERT INTO supply_supplier_payments (id, tenant_id, supplier_id, supplier_document_id, supplier_order_id, payment_type, status, payment_date, amount, currency, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'settlement-pg', :supplier, :document, :order, 'POSTPAYMENT', 'RECORDED', CURRENT_DATE, :amount, 'RUB', 95301, now(), 95301)"), {"id": payment_id, "supplier": supplier_id, "document": invoice_id, "order": order_id, "amount": amount})
            before = connection.scalar(text("SELECT sum(amount) FROM supply_supplier_payments WHERE supplier_document_id=:document AND status='RECORDED'"), {"document": invoice_id})
            self.assertEqual(before, Decimal("100.000000"))

        command.upgrade(self.config, "20260917_0053")
        self.assertEqual(self.revision(), "20260917_0053")
        with self.engine.connect() as connection:
            invoice = connection.execute(text("SELECT financial_role, obligation_id FROM supply_supplier_documents WHERE id=:id"), {"id": invoice_id}).one()
            delivery = connection.execute(text("SELECT financial_role, obligation_id FROM supply_supplier_documents WHERE id=:id"), {"id": delivery_id}).one()
            self.assertEqual(invoice.financial_role, "PAYABLE")
            self.assertIsNotNone(invoice.obligation_id)
            self.assertEqual(delivery.financial_role, "SUPPORTING")
            self.assertIsNone(delivery.obligation_id)
            upd = connection.execute(text("SELECT financial_role, obligation_id FROM supply_supplier_documents WHERE id=:id"), {"id": upd_id}).one()
            self.assertEqual(upd.financial_role, "PAYABLE")
            self.assertIsNotNone(upd.obligation_id)
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM supply_supplier_obligations")), 2)
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM supply_supplier_documents WHERE financial_role='SUPPORTING' AND obligation_id IS NULL")), 4)
            after = connection.scalar(text("SELECT sum(amount) FROM supply_supplier_payment_allocations WHERE supplier_document_id=:document AND status='ACTIVE'"), {"document": invoice_id})
            self.assertEqual(after, Decimal("100.000000"))
        inspector = inspect(self.engine)
        self.assertIn("uq_supply_supplier_documents_active_payable_obligation", {row["name"] for row in inspector.get_indexes("supply_supplier_documents")})
        self.assertIn("ck_supply_payment_allocations_amount", {row["name"] for row in inspector.get_check_constraints("supply_supplier_payment_allocations")})

        command.downgrade(self.config, "20260917_0052")
        self.assertEqual(self.revision(), "20260917_0052")
        command.upgrade(self.config, "20260917_0053")
        self.assertEqual(self.revision(), "20260917_0053")

        prepayment_id = uuid4()
        obligation_ids = [uuid4(), uuid4()]
        document_ids = [uuid4(), uuid4()]
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO supply_supplier_payments (id, tenant_id, supplier_id, supplier_order_id, payment_type, status, payment_date, amount, currency, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'settlement-pg', :supplier, :order, 'PREPAYMENT', 'RECORDED', CURRENT_DATE, 100, 'RUB', 95301, now(), 95301)"), {"id": prepayment_id, "supplier": supplier_id, "order": order_id})
            for obligation_id, document_id, number in zip(obligation_ids, document_ids, ("INV-C1", "INV-C2")):
                connection.execute(text("INSERT INTO supply_supplier_obligations (id, tenant_id, supplier_id, supplier_order_id, status, created_by_user_id) VALUES (:id, 'settlement-pg', :supplier, :order, 'ACTIVE', 95301)"), {"id": obligation_id, "supplier": supplier_id, "order": order_id})
                connection.execute(text("INSERT INTO supply_supplier_documents (id, tenant_id, supplier_order_id, supplier_id, obligation_id, document_type, financial_role, document_number, document_date, status, supplier_display_name_snapshot, currency, total_amount, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'settlement-pg', :order, :supplier, :obligation, 'INVOICE', 'PAYABLE', :number, CURRENT_DATE, 'RECORDED', 'Settlement Supplier', 'RUB', 100, 95301, now(), 95301)"), {"id": document_id, "order": order_id, "supplier": supplier_id, "obligation": obligation_id, "number": number})

        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        barrier = Barrier(2)
        def allocate(document_id):
            with sessions() as session:
                barrier.wait()
                try:
                    return create_allocation(session, SupplySupplierPaymentAllocationCreate(payment_id=prepayment_id, supplier_document_id=document_id, amount=Decimal("70")), tenant_id="settlement-pg", user_id=95301)
                except SupplierSettlementValidationError:
                    return "CONFLICT"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in (pool.submit(allocate, document_ids[0]), pool.submit(allocate, document_ids[1]))]
        allocations = [row for row in results if row != "CONFLICT"]
        self.assertEqual(len(allocations), 1)
        self.assertEqual(results.count("CONFLICT"), 1)
        with sessions() as session:
            reverse_allocation(
                session, allocations[0].id, reason="Partial concurrency refund",
                amount=Decimal("20"), tenant_id="settlement-pg", user_id=95301,
            )

        refund_barrier = Barrier(2)
        def refund():
            with sessions() as session:
                refund_barrier.wait()
                try:
                    return create_adjustment(session, SupplySupplierSettlementAdjustmentCreate(supplier_id=supplier_id, supplier_payment_id=prepayment_id, type="SUPPLIER_REFUND", amount=Decimal("40"), effective_date=date.today()), tenant_id="settlement-pg", user_id=95301)
                except SupplierSettlementValidationError:
                    return "CONFLICT"
        with ThreadPoolExecutor(max_workers=2) as pool:
            refunds = [future.result(timeout=15) for future in (pool.submit(refund), pool.submit(refund))]
        self.assertEqual(refunds.count("CONFLICT"), 1)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT sum(amount) FROM supply_supplier_payment_allocations WHERE payment_id=:payment AND status='ACTIVE'"), {"payment": prepayment_id}), Decimal("50.000000"))
            self.assertEqual(connection.scalar(text("SELECT reversed_amount FROM supply_supplier_payment_allocations WHERE id=:allocation"), {"allocation": allocations[0].id}), Decimal("20.000000"))
            self.assertEqual(connection.scalar(text("SELECT sum(amount) FROM supply_supplier_settlement_adjustments WHERE supplier_payment_id=:payment"), {"payment": prepayment_id}), Decimal("40.000000"))


if __name__ == "__main__":
    unittest.main()
