import os
import unittest
from pathlib import Path
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

from app.core.config import settings


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplySupplierOrderMessagePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql") or url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Migration test accepts only local eos_supply_migration_test")
        cls.engine = create_engine(TEST_DATABASE_URL)
        if inspect(cls.engine).get_table_names():
            cls.engine.dispose()
            raise RuntimeError("Migration test database must be empty")
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        cls.previous_settings = (
            settings.postgres_db, settings.postgres_user,
            settings.postgres_password, settings.postgres_host,
            settings.postgres_port,
        )
        settings.postgres_db, settings.postgres_user = url.database, url.username or ""
        settings.postgres_password, settings.postgres_host = url.password or "", url.host or ""
        settings.postgres_port = url.port or 5432

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "previous_settings"):
            (
                settings.postgres_db, settings.postgres_user,
                settings.postgres_password, settings.postgres_host,
                settings.postgres_port,
            ) = cls.previous_settings

    def revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_migration_cycle_and_atomic_snapshot_constraint(self) -> None:
        command.upgrade(self.config, "20260915_0043")
        self.assertEqual(self.revision(), "20260915_0043")
        command.upgrade(self.config, "20260915_0044")
        self.assertEqual(self.revision(), "20260915_0044")
        command.downgrade(self.config, "20260915_0043")
        self.assertEqual(self.revision(), "20260915_0043")
        command.upgrade(self.config, "20260915_0044")

        columns = {column["name"] for column in inspect(self.engine).get_columns("supply_supplier_orders")}
        self.assertTrue({
            "recipient_email_snapshot", "recipient_name_snapshot",
            "responsible_name_snapshot", "responsible_phone_snapshot",
        }.issubset(columns))
        constraints = {item["name"] for item in inspect(self.engine).get_check_constraints("supply_supplier_orders")}
        self.assertIn("ck_supply_supplier_orders_communication_snapshot", constraints)

        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) "
                "VALUES (94401, 'message-admin', 'Admin', 'x', 'message-test', true, true)"
            ))
            unit_id, product_id, supplier_id, request_id, order_id = (uuid4() for _ in range(5))
            connection.execute(text(
                "INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) "
                "VALUES (:id, 'message-test', 'MESSAGE_KG', 'Килограмм', 'кг', true, true)"
            ), {"id": unit_id})
            connection.execute(text(
                "INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) "
                "VALUES (:id, 'message-test', 'Сахар message', 'сахар message', :unit, true)"
            ), {"id": product_id, "unit": unit_id})
            connection.execute(text(
                "INSERT INTO supply_suppliers (id, tenant_id, display_name, order_email, is_active) "
                "VALUES (:id, 'message-test', 'Message Supplier', 'orders@example.test', true)"
            ), {"id": supplier_id})
            connection.execute(text(
                "INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) "
                "VALUES (:id, 'message-test', 'ZR-MESSAGE-PG', CURRENT_DATE, 'READY', 94401)"
            ), {"id": request_id})
            connection.execute(text(
                "INSERT INTO supply_supplier_orders "
                "(id, tenant_id, number, supplier_id, purchase_request_id, status, total_amount, currency, created_by_user_id, confirmed_at) "
                "VALUES (:id, 'message-test', 'PO-MESSAGE-PG', :supplier, :request, 'READY', 100, 'RUB', 94401, now())"
            ), {"id": order_id, "supplier": supplier_id, "request": request_id})

        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE supply_supplier_orders SET recipient_email_snapshot = 'orders@example.test' "
                "WHERE tenant_id = 'message-test'"
            ))

        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE supply_supplier_orders SET recipient_email_snapshot = 'orders@example.test', "
                "recipient_name_snapshot = 'Message Supplier', responsible_name_snapshot = 'Admin', "
                "responsible_phone_snapshot = '+7 900 000-00-00' WHERE tenant_id = 'message-test'"
            ))


if __name__ == "__main__":
    unittest.main()
