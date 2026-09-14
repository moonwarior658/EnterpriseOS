import os
import unittest
from pathlib import Path

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.user import User


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplySupplierMinimumOrderPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql"):
            raise RuntimeError("Migration test requires PostgreSQL")
        if url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Migration test accepts only local eos_supply_migration_test")
        cls.previous_database_settings = (
            settings.postgres_db, settings.postgres_user,
            settings.postgres_password, settings.postgres_host,
            settings.postgres_port,
        )
        settings.postgres_db = url.database
        settings.postgres_user = url.username or ""
        settings.postgres_password = url.password or ""
        settings.postgres_host = url.host or ""
        settings.postgres_port = url.port or 5432
        cls.engine = create_engine(TEST_DATABASE_URL)
        tables = inspect(cls.engine).get_table_names()
        if tables:
            cls.engine.dispose()
            cls._restore_settings()
            raise RuntimeError(f"Migration test database must be empty; found: {tables}")
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "previous_database_settings"):
            cls._restore_settings()

    @classmethod
    def _restore_settings(cls) -> None:
        (
            settings.postgres_db, settings.postgres_user,
            settings.postgres_password, settings.postgres_host,
            settings.postgres_port,
        ) = cls.previous_database_settings

    def _revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_cycle_constraint_values_and_supplier_api(self) -> None:
        command.upgrade(self.alembic_config, "20260914_0041")
        self.assertEqual(self._revision(), "20260914_0041")
        command.upgrade(self.alembic_config, "20260914_0042")
        self.assertEqual(self._revision(), "20260914_0042")
        command.downgrade(self.alembic_config, "20260914_0041")
        self.assertEqual(self._revision(), "20260914_0041")
        command.upgrade(self.alembic_config, "20260914_0042")
        self.assertEqual(self._revision(), "20260914_0042")

        with self.engine.begin() as connection:
            for suffix, amount in (("null", None), ("zero", "0"), ("positive", "10000.25")):
                connection.execute(
                    text(
                        "INSERT INTO supply_suppliers "
                        "(id, tenant_id, display_name, minimum_order_amount) "
                        "VALUES (gen_random_uuid(), 'migration-check', :name, :amount)"
                    ),
                    {"name": suffix, "amount": amount},
                )
        with self.assertRaises(IntegrityError) as raised:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO supply_suppliers "
                        "(id, tenant_id, display_name, minimum_order_amount) "
                        "VALUES (gen_random_uuid(), 'migration-check', 'negative', -0.01)"
                    )
                )
        self.assertIn(
            "ck_supply_suppliers_minimum_order_amount", str(raised.exception)
        )

        with self.sessions.begin() as session:
            session.add(User(
                id=92001, username="minimum-admin", display_name="Admin",
                hashed_password="unused", tenant_id="eclair",
                is_active=True, is_admin=True,
            ))

        def override_get_db():
            with self.sessions() as session:
                yield session

        def override_current_user():
            with self.sessions() as session:
                return session.get(User, 92001)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        app.openapi_schema = None
        client = TestClient(app)
        created = client.post(
            "/supply/suppliers",
            json={"display_name": "PG поставщик", "minimum_order_amount": "7500.50"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["minimum_order_amount"], "7500.50")
        cleared = client.patch(
            f"/supply/suppliers/{created.json()['id']}",
            json={"minimum_order_amount": None},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["minimum_order_amount"])


if __name__ == "__main__":
    unittest.main()
