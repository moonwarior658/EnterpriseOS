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
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.schemas.supplier_payment import SupplySupplierPaymentCreate
from app.supply.supplier_payments import (
    SupplierPaymentConflictError,
    SupplierPaymentStateError,
    create_payment,
    record_payment,
)


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplySupplierPaymentsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if (
            not url.drivername.startswith("postgresql")
            or url.host not in ALLOWED_HOSTS
            or url.database != EXPECTED_DATABASE_NAME
        ):
            raise RuntimeError("Migration test accepts only local eos_supply_migration_test")
        cls.previous_settings = (
            settings.postgres_db, settings.postgres_user, settings.postgres_password,
            settings.postgres_host, settings.postgres_port,
        )
        settings.postgres_db, settings.postgres_user = url.database, url.username or ""
        settings.postgres_password, settings.postgres_host = url.password or "", url.host or ""
        settings.postgres_port = url.port or 5432
        cls.engine = create_engine(TEST_DATABASE_URL)
        if inspect(cls.engine).get_table_names():
            cls.engine.dispose()
            raise RuntimeError("Migration test database must be empty")
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "previous_settings"):
            (
                settings.postgres_db, settings.postgres_user, settings.postgres_password,
                settings.postgres_host, settings.postgres_port,
            ) = cls.previous_settings

    def revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_cycle_constraints_duplicate_concurrency_and_row_lock(self) -> None:
        command.upgrade(self.config, "20260917_0051")
        command.upgrade(self.config, "20260917_0052")
        self.assertEqual(self.revision(), "20260917_0052")
        command.downgrade(self.config, "20260917_0051")
        self.assertEqual(self.revision(), "20260917_0051")
        self.assertNotIn("supply_supplier_payments", inspect(self.engine).get_table_names())
        command.upgrade(self.config, "20260917_0052")
        self.assertEqual(self.revision(), "20260917_0052")

        inspector = inspect(self.engine)
        indexes = {item["name"]: item for item in inspector.get_indexes("supply_supplier_payments")}
        self.assertTrue(indexes["uq_supply_supplier_payments_order_identity"]["unique"])
        self.assertIn("payment_order_number IS NOT NULL", indexes["uq_supply_supplier_payments_order_identity"]["dialect_options"]["postgresql_where"])
        fks = {item["name"] for item in inspector.get_foreign_keys("supply_supplier_payments")}
        self.assertIn("fk_supply_supplier_payments_document_supplier_tenant", fks)
        self.assertIn("fk_supply_supplier_payments_order_supplier_tenant", fks)
        checks = {item["name"] for item in inspector.get_check_constraints("supply_supplier_payments")}
        self.assertIn("ck_supply_supplier_payments_amount", checks)
        self.assertIn("ck_supply_supplier_payments_order_fields", checks)
        self.assertIn("ck_supply_supplier_payments_recorded", checks)

        supplier_id, request_id, order_id, document_id = (uuid4() for _ in range(4))
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) VALUES (95201, 'payment-pg-admin', 'Payment Admin', 'x', 'payment-pg', true, true)"))
            connection.execute(text("INSERT INTO supply_suppliers (id, tenant_id, display_name, is_active) VALUES (:id, 'payment-pg', 'Payment PG Supplier', true)"), {"id": supplier_id})
            connection.execute(text("INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) VALUES (:id, 'payment-pg', 'ZR-PAY-PG', CURRENT_DATE, 'READY', 95201)"), {"id": request_id})
            connection.execute(text("INSERT INTO supply_supplier_orders (id, tenant_id, number, supplier_id, purchase_request_id, status, total_amount, currency, created_by_user_id, confirmed_at, sent_at) VALUES (:id, 'payment-pg', 'PO-PAY-PG', :supplier, :request, 'SENT', 100, 'RUB', 95201, now(), now())"), {"id": order_id, "supplier": supplier_id, "request": request_id})
            connection.execute(text("INSERT INTO supply_supplier_documents (id, tenant_id, supplier_order_id, supplier_id, document_type, document_number, document_date, payment_due_date, status, supplier_display_name_snapshot, currency, total_amount, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'payment-pg', :order, :supplier, 'INVOICE', 'INV-PAY-PG', CURRENT_DATE, CURRENT_DATE, 'RECORDED', 'Payment PG Supplier', 'RUB', 100, 95201, now(), 95201)"), {"id": document_id, "order": order_id, "supplier": supplier_id})

        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("INSERT INTO supply_supplier_payments (id, tenant_id, supplier_id, payment_type, status, payment_date, amount, currency, created_by_user_id) VALUES (:id, 'payment-pg', :supplier, 'PREPAYMENT', 'DRAFT', CURRENT_DATE, 0, 'RUB', 95201)"), {"id": uuid4(), "supplier": supplier_id})
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("INSERT INTO supply_supplier_payments (id, tenant_id, supplier_id, supplier_order_id, payment_type, status, payment_date, amount, currency, created_by_user_id) VALUES (:id, 'other-tenant', :supplier, :order, 'PREPAYMENT', 'DRAFT', CURRENT_DATE, 1, 'RUB', 95201)"), {"id": uuid4(), "supplier": supplier_id, "order": order_id})
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("INSERT INTO supply_supplier_payments (id, tenant_id, supplier_id, supplier_order_id, payment_type, status, payment_date, amount, currency, payment_order_number, created_by_user_id) VALUES (:id, 'payment-pg', :supplier, :order, 'PREPAYMENT', 'DRAFT', CURRENT_DATE, 1, 'RUB', 'BAD-PAIR', 95201)"), {"id": uuid4(), "supplier": supplier_id, "order": order_id})

        command.upgrade(self.config, "20260917_0053")
        self.assertEqual(self.revision(), "20260917_0053")

        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        payload = SupplySupplierPaymentCreate(
            supplier_id=supplier_id, supplier_document_id=document_id,
            supplier_order_id=order_id, payment_type="POSTPAYMENT",
            payment_date=date(2026, 9, 17), amount=Decimal("30.000001"),
            payment_order_number="PG-ORDER-1", payment_order_date=date(2026, 9, 17),
        )
        with sessions() as session:
            payment = create_payment(session, payload, tenant_id="payment-pg", user_id=95201)
        with sessions() as session, self.assertRaises(SupplierPaymentConflictError):
            create_payment(session, payload, tenant_id="payment-pg", user_id=95201)

        statements: list[str] = []

        def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        barrier = Barrier(2)

        def record() -> str:
            with sessions() as session:
                barrier.wait()
                try:
                    return record_payment(
                        session, payment.id, tenant_id="payment-pg", user_id=95201,
                    ).status
                except SupplierPaymentStateError:
                    return "CONFLICT"

        event.listen(self.engine, "before_cursor_execute", capture_sql)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result(timeout=15) for future in (
                    pool.submit(record), pool.submit(record),
                )]
        finally:
            event.remove(self.engine, "before_cursor_execute", capture_sql)
        self.assertEqual(sorted(results), ["CONFLICT", "RECORDED"])
        locking = [
            statement for statement in statements
            if "FOR UPDATE" in statement.upper() and "supply_supplier_payments" in statement
        ]
        self.assertTrue(locking)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_supplier_payments WHERE status = 'RECORDED'"
            )), 1)


if __name__ == "__main__":
    unittest.main()
