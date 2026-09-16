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
from app.supply.supplier_orders import (
    cancel_supplier_order,
    create_supplier_orders,
    mark_supplier_order_ready,
)


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplySupplierOrdersPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql") or url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Migration test accepts only local eos_supply_migration_test")
        cls.previous_settings = (settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port)
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
            settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port = cls.previous_settings

    def revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_migration_constraints_and_concurrent_idempotency(self) -> None:
        command.upgrade(self.config, "20260914_0042")
        self.assertEqual(self.revision(), "20260914_0042")
        command.upgrade(self.config, "20260915_0043")
        self.assertEqual(self.revision(), "20260915_0043")
        command.downgrade(self.config, "20260914_0042")
        self.assertEqual(self.revision(), "20260914_0042")
        command.upgrade(self.config, "20260915_0043")
        command.upgrade(self.config, "head")

        inspector = inspect(self.engine)
        self.assertIn("supply_supplier_orders", inspector.get_table_names())
        self.assertIn("supply_supplier_order_lines", inspector.get_table_names())
        self.assertIn("uq_supply_supplier_order_lines_active_allocation", {item["name"] for item in inspector.get_indexes("supply_supplier_order_lines")})

        unit_id, product_id, supplier_id, relation_id = uuid4(), uuid4(), uuid4(), uuid4()
        request_id, line_id, allocation_id = uuid4(), uuid4(), uuid4()
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) VALUES (94001, 'order-admin', 'Admin', 'x', 'order-test', true, true)"))
            connection.execute(text("INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) VALUES (:id, 'order-test', 'ORDER_KG', 'Килограмм', 'кг', true, true)"), {"id": unit_id})
            connection.execute(text("INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) VALUES (:id, 'order-test', 'Сахар order', 'сахар order', :unit, true)"), {"id": product_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_suppliers (id, tenant_id, display_name, minimum_order_amount, is_active) VALUES (:id, 'order-test', 'Order Supplier', 20000, true)"), {"id": supplier_id})
            connection.execute(text("INSERT INTO supply_product_suppliers (id, tenant_id, product_id, supplier_id, role, priority, package_quantity, package_unit_id, price_per_package, currency, is_available, is_active) VALUES (:id, 'order-test', :product, :supplier, 'PRIMARY', 10, 12, :unit, 4956, 'RUB', true, true)"), {"id": relation_id, "product": product_id, "supplier": supplier_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) VALUES (:id, 'order-test', 'ZR-ORDER-PG', CURRENT_DATE, 'READY', 94001)"), {"id": request_id})
            connection.execute(text("INSERT INTO supply_purchase_request_lines (id, tenant_id, purchase_request_id, product_id, quantity, unit_id, manual_future_quantity) VALUES (:id, 'order-test', :request, :product, 36, :unit, 36)"), {"id": line_id, "request": request_id, "product": product_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_purchase_allocations (id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) VALUES (:id, 'order-test', :line, :relation, 36, 12, :unit, 3, 4956, 413, 'RUB', 14868, 'CONFIRMED')"), {"id": allocation_id, "line": line_id, "relation": relation_id, "unit": unit_id})

        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        barrier = Barrier(2)
        def generate() -> tuple[str, ...]:
            with sessions() as session:
                barrier.wait()
                return tuple(str(item.id) for item in create_supplier_orders(session, request_id, tenant_id="order-test", user_id=94001))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in (pool.submit(generate), pool.submit(generate))]
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(results[0]), 1)

        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM supply_supplier_orders")), 1)
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM supply_supplier_order_lines")), 1)
            order_id = connection.scalar(text("SELECT id FROM supply_supplier_orders"))
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("INSERT INTO supply_supplier_order_lines (id, tenant_id, supplier_order_id, source_allocation_id, product_id, product_name_snapshot, packages_count, package_quantity_snapshot, package_unit_id_snapshot, quantity_base, price_per_package_snapshot, base_unit_price_snapshot, planned_amount, currency, is_active_owner) VALUES (:id, 'order-test', :order_id, :allocation, :product, 'Сахар order', 3, 12, :unit, 36, 4956, 413, 14868, 'RUB', true)"), {"id": uuid4(), "order_id": order_id, "allocation": allocation_id, "product": product_id, "unit": unit_id})

        with sessions() as session:
            cancel_supplier_order(session, order_id, tenant_id="order-test")
            recreated = create_supplier_orders(session, request_id, tenant_id="order-test", user_id=94001)
            self.assertEqual(len(recreated), 1)
            self.assertNotEqual(str(recreated[0].id), str(order_id))

        statements: list[str] = []

        def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture_sql)
        try:
            with sessions() as session:
                ready = mark_supplier_order_ready(
                    session, recreated[0].id, tenant_id="order-test"
                )
        finally:
            event.remove(self.engine, "before_cursor_execute", capture_sql)

        self.assertEqual(ready.status, "READY")
        locking_statements = [
            statement for statement in statements
            if "FOR UPDATE" in statement.upper()
            and "supply_supplier_orders" in statement
        ]
        self.assertEqual(len(locking_statements), 1)
        self.assertIn(
            "FOR UPDATE OF supply_supplier_orders",
            locking_statements[0],
        )


if __name__ == "__main__":
    unittest.main()
