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
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from app.core.config import settings


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplyPurchaseRequestsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql"):
            raise RuntimeError("Migration test requires PostgreSQL")
        if url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Migration test accepts only the isolated local database")
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
        if inspect(cls.engine).get_table_names():
            cls.engine.dispose()
            raise RuntimeError("Migration test database must be empty")
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "previous_database_settings"):
            (
                settings.postgres_db, settings.postgres_user,
                settings.postgres_password, settings.postgres_host,
                settings.postgres_port,
            ) = cls.previous_database_settings

    def revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_migration_cycle_and_postgresql_constraints(self) -> None:
        command.upgrade(self.config, "20260907_0037")
        command.upgrade(self.config, "20260914_0038")
        self.assertEqual(self.revision(), "20260914_0038")
        command.downgrade(self.config, "20260907_0037")
        self.assertNotIn("supply_purchase_requests", inspect(self.engine).get_table_names())
        command.upgrade(self.config, "head")
        self.assertEqual(self.revision(), "20260914_0038")

        inspector = inspect(self.engine)
        request_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("supply_purchase_requests")
        }
        line_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("supply_purchase_request_lines")
        }
        self.assertIn(("tenant_id", "number"), request_uniques)
        self.assertIn(
            ("tenant_id", "purchase_request_id", "product_id", "unit_id"),
            line_uniques,
        )
        line_fks = {item["name"] for item in inspector.get_foreign_keys("supply_purchase_request_lines")}
        self.assertTrue({
            "fk_supply_purchase_request_lines_request_tenant",
            "fk_supply_purchase_request_lines_product_tenant",
            "fk_supply_purchase_request_lines_unit_tenant",
        }.issubset(line_fks))
        source_checks = {item["name"] for item in inspector.get_check_constraints("supply_purchase_request_line_sources")}
        self.assertTrue({
            "ck_supply_purchase_request_line_sources_type",
            "ck_supply_purchase_request_line_sources_quantity",
            "ck_supply_purchase_request_line_sources_reference",
        }.issubset(source_checks))


if __name__ == "__main__":
    unittest.main()
