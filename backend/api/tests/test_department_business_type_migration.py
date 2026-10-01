"""PostgreSQL proof for the current Department classification migration."""
import os
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from tests.postgres_test_support import reset_disposable_postgres_schema


TEST_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL, "SUPPLY_TEST_DATABASE_URL requires isolated PostgreSQL")
class DepartmentBusinessTypeMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_preserves_ids_and_unknowns(self) -> None:
        url = make_url(TEST_URL)
        self.assertIn(url.host, {"127.0.0.1", "localhost", "::1"})
        self.assertEqual(url.database, "eos_supply_migration_test")
        previous = (settings.postgres_db, settings.postgres_user,
                    settings.postgres_password, settings.postgres_host, settings.postgres_port)
        engine = create_engine(TEST_URL)
        try:
            reset_disposable_postgres_schema(engine)
            settings.postgres_db = url.database
            settings.postgres_user = url.username or ""
            settings.postgres_password = url.password or ""
            settings.postgres_host = url.host or ""
            settings.postgres_port = url.port or 5432
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            command.upgrade(config, "20260929_0062")
            with engine.begin() as connection:
                original_id = connection.scalar(text(
                    "SELECT id FROM departments WHERE tenant_id='eclair' AND code='М6А'"
                ))
                connection.execute(text(
                    "INSERT INTO departments (id, tenant_id, code, name, is_active, display_order) "
                    "VALUES ('dd6a1111-aaaa-4444-8888-000000000001', 'eclair', 'UNKNOWN', "
                    "'Неизвестно', true, 60)"
                ))
            command.upgrade(config, "20261001_0063")
            with engine.connect() as connection:
                rows = connection.execute(text(
                    "SELECT code, name, business_type, id FROM departments "
                    "WHERE tenant_id='eclair' ORDER BY display_order"
                )).all()
                by_code = {row.code: row for row in rows}
                self.assertEqual(by_code["И25"].id, original_id)
                self.assertEqual(by_code["И25"].name, "Игарская 25В")
                self.assertEqual(by_code["И25"].business_type, "RETAIL_POINT")
                self.assertEqual(by_code["М15"].business_type, "RETAIL_POINT")
                self.assertEqual(by_code["М35"].business_type, "RETAIL_POINT")
                self.assertEqual(by_code["ЦЕХ"].business_type, "PRODUCTION")
                self.assertEqual(by_code["ATO"].business_type, "AUTO")
                self.assertIsNone(by_code["UNKNOWN"].business_type)
            command.downgrade(config, "20260929_0062")
            with engine.connect() as connection:
                self.assertEqual(connection.scalar(text(
                    "SELECT id FROM departments WHERE tenant_id='eclair' AND code='М6А'"
                )), original_id)
            command.upgrade(config, "head")
            with engine.connect() as connection:
                self.assertEqual(connection.scalar(text(
                    "SELECT business_type FROM departments WHERE tenant_id='eclair' AND code='И25'"
                )), "RETAIL_POINT")
        finally:
            (settings.postgres_db, settings.postgres_user, settings.postgres_password,
             settings.postgres_host, settings.postgres_port) = previous
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
