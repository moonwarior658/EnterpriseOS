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
class SupplySupplierOrderEmailPostgresTests(unittest.TestCase):
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

    def test_cycle_constraints_indexes_and_sent_semantics(self) -> None:
        command.upgrade(self.config, "20260915_0044")
        self.assertEqual(self.revision(), "20260915_0044")
        command.upgrade(self.config, "20260915_0045")
        self.assertEqual(self.revision(), "20260915_0045")
        command.downgrade(self.config, "20260915_0044")
        self.assertEqual(self.revision(), "20260915_0044")
        command.upgrade(self.config, "20260915_0045")

        inspector = inspect(self.engine)
        constraints = {
            item["name"] for item in inspector.get_check_constraints(
                "supply_supplier_order_delivery_attempts"
            )
        }
        self.assertTrue({
            "ck_supply_supplier_order_delivery_attempts_number",
            "ck_supply_supplier_order_delivery_attempts_status",
            "ck_supply_supplier_order_delivery_attempts_timestamps",
        }.issubset(constraints))
        indexes = {item["name"]: item for item in inspector.get_indexes("supply_supplier_order_delivery_attempts")}
        self.assertTrue(indexes["uq_supply_supplier_order_delivery_attempts_active"]["unique"])

        user_id = 94501
        supplier_id, request_id, order_id, execution_id, attempt_id = (uuid4() for _ in range(5))
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) "
                "VALUES (:id, 'email-admin', 'Admin', 'x', 'email-test', true, true)"
            ), {"id": user_id})
            connection.execute(text(
                "INSERT INTO supply_suppliers (id, tenant_id, display_name, order_email, is_active) "
                "VALUES (:id, 'email-test', 'Email Supplier', 'orders@example.test', true)"
            ), {"id": supplier_id})
            connection.execute(text(
                "INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) "
                "VALUES (:id, 'email-test', 'ZR-EMAIL-PG', CURRENT_DATE, 'READY', :user_id)"
            ), {"id": request_id, "user_id": user_id})
            connection.execute(text(
                "INSERT INTO supply_supplier_orders "
                "(id, tenant_id, number, supplier_id, purchase_request_id, status, total_amount, currency, created_by_user_id, confirmed_at, "
                "recipient_email_snapshot, recipient_name_snapshot, responsible_name_snapshot, responsible_phone_snapshot) "
                "VALUES (:id, 'email-test', 'PO-EMAIL-PG', :supplier, :request, 'READY', 100, 'RUB', :user_id, now(), "
                "'orders@example.test', 'Email Supplier', 'Admin', '+7 900 000-00-00')"
            ), {"id": order_id, "supplier": supplier_id, "request": request_id, "user_id": user_id})
            connection.execute(text(
                "INSERT INTO automation_executions "
                "(execution_id, contract_version, automation_type, tenant_id, scope_type, recipients, status, requested_at, payload, attempt_count, max_attempts) "
                "VALUES (:id, '1.0', 'supply.supplier_order_email_send', 'email-test', 'company', '[]'::jsonb, 'pending', now(), '{}'::jsonb, 0, 3)"
            ), {"id": execution_id})
            connection.execute(text(
                "INSERT INTO supply_supplier_order_delivery_attempts "
                "(id, tenant_id, supplier_order_id, attempt_number, status, recipient_email, subject, body_text, automation_execution_id, idempotency_key, created_by_user_id) "
                "VALUES (:id, 'email-test', :order_id, 1, 'PENDING', 'orders@example.test', 'Заказ', 'Текст', :execution_id, 'email-key-1', :user_id)"
            ), {"id": attempt_id, "order_id": order_id, "execution_id": execution_id, "user_id": user_id})

        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            second_execution_id = uuid4()
            connection.execute(text(
                "INSERT INTO automation_executions "
                "(execution_id, contract_version, automation_type, tenant_id, scope_type, recipients, status, requested_at, payload, attempt_count, max_attempts) "
                "VALUES (:id, '1.0', 'supply.supplier_order_email_send', 'email-test', 'company', '[]'::jsonb, 'pending', now(), '{}'::jsonb, 0, 3)"
            ), {"id": second_execution_id})
            connection.execute(text(
                "UPDATE supply_supplier_orders SET status = 'SENT' WHERE id = :id"
            ), {"id": order_id})

        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO supply_supplier_order_delivery_attempts "
                "(id, tenant_id, supplier_order_id, attempt_number, status, recipient_email, subject, body_text, automation_execution_id, idempotency_key, created_by_user_id) "
                "VALUES (:id, 'email-test', :order_id, 2, 'PENDING', 'orders@example.test', 'Заказ', 'Текст', :execution_id, 'email-key-2', :user_id)"
            ), {"id": uuid4(), "order_id": order_id, "execution_id": second_execution_id, "user_id": user_id})

        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE supply_supplier_order_delivery_attempts SET status = 'SUCCEEDED', dispatched_at = now(), completed_at = now() WHERE id = :id"
            ), {"id": attempt_id})
            connection.execute(text(
                "UPDATE supply_supplier_orders SET status = 'SENT', sent_at = now() WHERE id = :id"
            ), {"id": order_id})


if __name__ == "__main__":
    unittest.main()
