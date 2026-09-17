import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
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
from app.schemas.supplier_document import SupplySupplierDocumentCreate
from app.supply.supplier_documents import (
    SupplierDocumentConflictError,
    SupplierDocumentStateError,
    create_document,
    record_document,
)


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplySupplierDocumentsPostgresTests(unittest.TestCase):
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

    def test_cycle_constraints_tenant_fk_concurrency_and_locking(self) -> None:
        command.upgrade(self.config, "20260917_0047")
        command.upgrade(self.config, "20260917_0048")
        self.assertEqual(self.revision(), "20260917_0048")
        command.downgrade(self.config, "20260917_0047")
        self.assertEqual(self.revision(), "20260917_0047")
        command.upgrade(self.config, "20260917_0048")

        inspector = inspect(self.engine)
        document_indexes = {
            item["name"]: item for item in inspector.get_indexes("supply_supplier_documents")
        }
        self.assertTrue(document_indexes["uq_supply_supplier_documents_identity"]["unique"])
        line_fks = {
            item["name"] for item in inspector.get_foreign_keys("supply_supplier_document_lines")
        }
        self.assertIn("fk_supply_supplier_document_lines_document_order_tenant", line_fks)
        self.assertIn("fk_supply_supplier_document_lines_confirmation_line_tenant", line_fks)
        self.assertIn("fk_supply_supplier_document_lines_unit_tenant", line_fks)
        line_checks = {
            item["name"] for item in inspector.get_check_constraints("supply_supplier_document_lines")
        }
        self.assertIn("ck_supply_supplier_document_lines_pricing_fields", line_checks)

        unit_id, product_id, supplier_id, relation_id = uuid4(), uuid4(), uuid4(), uuid4()
        request_id, request_line_id, allocation_id, order_id, order_line_id = (
            uuid4() for _ in range(5)
        )
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) VALUES (94801, 'document-admin', 'Admin', 'x', 'document-test', true, true)"))
            connection.execute(text("INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) VALUES (:id, 'document-test', 'DOC_KG', 'Килограмм', 'кг', true, true)"), {"id": unit_id})
            connection.execute(text("INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) VALUES (:id, 'document-test', 'Сахар document', 'сахар document', :unit, true)"), {"id": product_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_suppliers (id, tenant_id, display_name, inn, kpp, is_active) VALUES (:id, 'document-test', 'Document Supplier', '6671000000', '667101001', true)"), {"id": supplier_id})
            connection.execute(text("INSERT INTO supply_product_suppliers (id, tenant_id, product_id, supplier_id, role, priority, package_quantity, package_unit_id, price_per_package, currency, is_available, is_active) VALUES (:id, 'document-test', :product, :supplier, 'PRIMARY', 10, 12, :unit, 100, 'RUB', true, true)"), {"id": relation_id, "product": product_id, "supplier": supplier_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) VALUES (:id, 'document-test', 'ZR-DOC-PG', CURRENT_DATE, 'READY', 94801)"), {"id": request_id})
            connection.execute(text("INSERT INTO supply_purchase_request_lines (id, tenant_id, purchase_request_id, product_id, quantity, unit_id, manual_future_quantity) VALUES (:id, 'document-test', :request, :product, 24, :unit, 24)"), {"id": request_line_id, "request": request_id, "product": product_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_purchase_allocations (id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) VALUES (:id, 'document-test', :line, :relation, 24, 12, :unit, 2, 100, 8.333333, 'RUB', 200, 'CONFIRMED')"), {"id": allocation_id, "line": request_line_id, "relation": relation_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_supplier_orders (id, tenant_id, number, supplier_id, purchase_request_id, status, planned_delivery_date, total_amount, currency, created_by_user_id, confirmed_at, sent_at) VALUES (:id, 'document-test', 'PO-DOC-PG', :supplier, :request, 'SENT', CURRENT_DATE, 200, 'RUB', 94801, now(), now())"), {"id": order_id, "supplier": supplier_id, "request": request_id})
            connection.execute(text("INSERT INTO supply_supplier_order_lines (id, tenant_id, supplier_order_id, source_allocation_id, product_id, product_name_snapshot, packages_count, package_quantity_snapshot, package_unit_id_snapshot, quantity_base, price_per_package_snapshot, base_unit_price_snapshot, planned_amount, currency, is_active_owner) VALUES (:id, 'document-test', :order, :allocation, :product, 'Сахар document', 2, 12, :unit, 24, 100, 8.333333, 200, 'RUB', true)"), {"id": order_line_id, "order": order_id, "allocation": allocation_id, "product": product_id, "unit": unit_id})

        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        payload = SupplySupplierDocumentCreate(
            document_type="INVOICE", document_number="INV-PG-1", document_date=date(2026, 9, 17),
        )
        with sessions() as session:
            document = create_document(
                session, order_id, payload, tenant_id="document-test", user_id=94801,
            )
        self.assertEqual(document.total_amount, 200)

        with sessions() as session, self.assertRaises(SupplierDocumentConflictError):
            create_document(
                session, order_id, payload, tenant_id="document-test", user_id=94801,
            )

        duplicate_barrier = Barrier(2)
        concurrent_payload = SupplySupplierDocumentCreate(
            document_type="DELIVERY_NOTE", document_number="DN-PG-CONCURRENT",
            document_date=date(2026, 9, 17),
        )

        def create_duplicate() -> str:
            with sessions() as session:
                duplicate_barrier.wait()
                try:
                    create_document(
                        session, order_id, concurrent_payload,
                        tenant_id="document-test", user_id=94801,
                    )
                    return "CREATED"
                except SupplierDocumentConflictError:
                    return "CONFLICT"

        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicate_results = [future.result(timeout=15) for future in (
                pool.submit(create_duplicate), pool.submit(create_duplicate),
            )]
        self.assertEqual(sorted(duplicate_results), ["CONFLICT", "CREATED"])

        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO supply_supplier_document_lines "
                "(id, tenant_id, supplier_document_id, supplier_order_id, product_name_snapshot, "
                "pricing_basis, packages_count, price_per_package, line_amount, currency) "
                "VALUES (:id, 'document-test', :document, :order, 'Bad amount', "
                "'PACKAGE', 2, 100, 199, 'RUB')"
            ), {"id": uuid4(), "document": document.id, "order": order_id})
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO supply_supplier_document_lines "
                "(id, tenant_id, supplier_document_id, supplier_order_id, product_name_snapshot, "
                "pricing_basis, quantity_base, package_unit_id_snapshot, unit_price, line_amount, currency) "
                "VALUES (:id, 'other-tenant', :document, :order, 'Wrong tenant', "
                "'UNIT', 1, :unit, 1, 1, 'RUB')"
            ), {"id": uuid4(), "document": document.id, "order": order_id, "unit": unit_id})

        statements: list[str] = []

        def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        barrier = Barrier(2)

        def record() -> str:
            with sessions() as session:
                barrier.wait()
                try:
                    result = record_document(
                        session, document.id, tenant_id="document-test", user_id=94801,
                    )
                    return result.status
                except SupplierDocumentStateError:
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
            if "FOR UPDATE" in statement.upper() and "supply_supplier_orders" in statement
        ]
        self.assertTrue(locking)
        self.assertTrue(any("FOR UPDATE OF supply_supplier_orders" in statement for statement in locking))
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_supplier_documents WHERE status = 'RECORDED'"
            )), 1)


if __name__ == "__main__":
    unittest.main()
