import os
import unittest
from concurrent.futures import ThreadPoolExecutor
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
from app.schemas.supplier_acceptance import SupplySupplierAcceptanceCreate
from app.supply.supplier_acceptances import (
    SupplierAcceptanceConflictError, create_acceptance, record_acceptance,
)

TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplySupplierAcceptancesPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql") or url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Migration test accepts only local eos_supply_migration_test")
        cls.previous_settings = (settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port)
        settings.postgres_db, settings.postgres_user = url.database, url.username or ""
        settings.postgres_password, settings.postgres_host = url.password or "", url.host or ""
        settings.postgres_port = url.port or 5432
        cls.engine = create_engine(TEST_DATABASE_URL)
        if inspect(cls.engine).get_table_names():
            cls.engine.dispose(); raise RuntimeError("Migration test database must be empty")
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        (settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port) = cls.previous_settings

    def revision(self):
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_cycle_constraints_tenant_safety_and_concurrent_remaining_guard(self) -> None:
        command.upgrade(self.config, "20260917_0048")
        command.upgrade(self.config, "20260917_0049")
        self.assertEqual(self.revision(), "20260917_0049")
        command.downgrade(self.config, "20260917_0048")
        self.assertEqual(self.revision(), "20260917_0048")
        command.upgrade(self.config, "20260917_0049")

        inspector = inspect(self.engine)
        self.assertIn("ck_supply_supplier_acceptance_lines_equation", {x["name"] for x in inspector.get_check_constraints("supply_supplier_acceptance_lines")})
        self.assertIn("fk_supply_supplier_acceptance_lines_document_line_tenant", {x["name"] for x in inspector.get_foreign_keys("supply_supplier_acceptance_lines")})
        self.assertTrue({x["name"]: x for x in inspector.get_indexes("supply_supplier_acceptance_lines")}["uq_supply_supplier_acceptance_lines_document_identity"]["unique"])

        unit_id, product_id, supplier_id, relation_id = uuid4(), uuid4(), uuid4(), uuid4()
        request_id, request_line_id, allocation_id, order_id, order_line_id = (uuid4() for _ in range(5))
        document_id, document_line_id = uuid4(), uuid4()
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) VALUES (94901, 'accept-admin', 'Admin', 'x', 'accept-test', true, true)"))
            c.execute(text("INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) VALUES (:id, 'accept-test', 'ACC_KG', 'Килограмм', 'кг', true, true)"), {"id": unit_id})
            c.execute(text("INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) VALUES (:id, 'accept-test', 'Сахар acceptance', 'сахар acceptance', :unit, true)"), {"id": product_id, "unit": unit_id})
            c.execute(text("INSERT INTO supply_suppliers (id, tenant_id, display_name, inn, kpp, is_active) VALUES (:id, 'accept-test', 'Acceptance Supplier', '6671000001', '667101001', true)"), {"id": supplier_id})
            c.execute(text("INSERT INTO supply_product_suppliers (id, tenant_id, product_id, supplier_id, role, priority, package_quantity, package_unit_id, price_per_package, currency, is_available, is_active) VALUES (:id, 'accept-test', :product, :supplier, 'PRIMARY', 10, 12, :unit, 100, 'RUB', true, true)"), {"id": relation_id, "product": product_id, "supplier": supplier_id, "unit": unit_id})
            c.execute(text("INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) VALUES (:id, 'accept-test', 'ZR-ACC-PG', CURRENT_DATE, 'READY', 94901)"), {"id": request_id})
            c.execute(text("INSERT INTO supply_purchase_request_lines (id, tenant_id, purchase_request_id, product_id, quantity, unit_id, manual_future_quantity) VALUES (:id, 'accept-test', :request, :product, 24, :unit, 24)"), {"id": request_line_id, "request": request_id, "product": product_id, "unit": unit_id})
            c.execute(text("INSERT INTO supply_purchase_allocations (id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) VALUES (:id, 'accept-test', :line, :relation, 24, 12, :unit, 2, 100, 8.333333, 'RUB', 200, 'CONFIRMED')"), {"id": allocation_id, "line": request_line_id, "relation": relation_id, "unit": unit_id})
            c.execute(text("INSERT INTO supply_supplier_orders (id, tenant_id, number, supplier_id, purchase_request_id, status, total_amount, currency, created_by_user_id, confirmed_at, sent_at) VALUES (:id, 'accept-test', 'PO-ACC-PG', :supplier, :request, 'SENT', 200, 'RUB', 94901, now(), now())"), {"id": order_id, "supplier": supplier_id, "request": request_id})
            c.execute(text("INSERT INTO supply_supplier_order_lines (id, tenant_id, supplier_order_id, source_allocation_id, product_id, product_name_snapshot, packages_count, package_quantity_snapshot, package_unit_id_snapshot, quantity_base, price_per_package_snapshot, base_unit_price_snapshot, planned_amount, currency, is_active_owner) VALUES (:id, 'accept-test', :order, :allocation, :product, 'Сахар acceptance', 2, 12, :unit, 24, 100, 8.333333, 200, 'RUB', true)"), {"id": order_line_id, "order": order_id, "allocation": allocation_id, "product": product_id, "unit": unit_id})
            c.execute(text("INSERT INTO supply_supplier_documents (id, tenant_id, supplier_order_id, supplier_id, document_type, document_number, document_date, status, supplier_display_name_snapshot, currency, total_amount, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'accept-test', :order, :supplier, 'DELIVERY_NOTE', 'DN-ACC-PG', CURRENT_DATE, 'RECORDED', 'Acceptance Supplier', 'RUB', 200, 94901, now(), 94901)"), {"id": document_id, "order": order_id, "supplier": supplier_id})
            c.execute(text("INSERT INTO supply_supplier_document_lines (id, tenant_id, supplier_document_id, supplier_order_id, supplier_order_line_id, product_name_snapshot, pricing_basis, package_quantity_snapshot, package_unit_id_snapshot, unit_name_snapshot, packages_count, quantity_base, price_per_package, line_amount, currency) VALUES (:id, 'accept-test', :document, :order, :order_line, 'Сахар acceptance', 'PACKAGE', 12, :unit, 'кг', 2, 24, 100, 200, 'RUB')"), {"id": document_line_id, "document": document_id, "order": order_id, "order_line": order_line_id, "unit": unit_id})

        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with sessions() as session:
            first = create_acceptance(session, order_id, SupplySupplierAcceptanceCreate(supplier_document_id=document_id), tenant_id="accept-test", user_id=94901)
        with sessions() as session:
            second = create_acceptance(session, order_id, SupplySupplierAcceptanceCreate(supplier_document_id=document_id), tenant_id="accept-test", user_id=94901)
        self.assertEqual(first.lines[0].documented_quantity, 24)
        barrier = Barrier(2); statements: list[str] = []
        def capture(_c, _cursor, statement, _parameters, _context, _executemany): statements.append(statement)
        def record(identifier):
            with sessions() as session:
                barrier.wait()
                try:
                    record_acceptance(session, identifier, tenant_id="accept-test", user_id=94901); return "RECORDED"
                except SupplierAcceptanceConflictError: return "CONFLICT"
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result(timeout=15) for future in (pool.submit(record, first.id), pool.submit(record, second.id))]
        finally: event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(sorted(results), ["CONFLICT", "RECORDED"])
        self.assertTrue(any("FOR UPDATE" in statement.upper() and "supply_supplier_document_lines" in statement for statement in statements))

        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(text("INSERT INTO supply_supplier_acceptance_lines (id, tenant_id, acceptance_id, supplier_order_id, product_name_snapshot, unit_id, received_quantity, accepted_quantity, rejected_quantity, currency) VALUES (:id, 'accept-test', :acceptance, :order, 'Bad equation', :unit, 10, 8, 1, 'RUB')"), {"id": uuid4(), "acceptance": first.id, "order": order_id, "unit": unit_id})


if __name__ == "__main__": unittest.main()
