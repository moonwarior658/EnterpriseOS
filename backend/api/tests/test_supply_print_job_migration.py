import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260812_0033_add_supply_print_jobs.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("supply_print_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supply print migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyPrintJobMigrationTests(unittest.TestCase):
    def test_revision_follows_0032(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260812_0033")
        self.assertEqual(migration.down_revision, "20260812_0032")

    def test_upgrade_creates_guarded_print_job_table(self) -> None:
        engine = sa.create_engine("sqlite://")
        with engine.begin() as connection:
            migration = load_migration()
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
        inspector = sa.inspect(engine)
        columns = {column["name"] for column in inspector.get_columns(
            "supply_print_jobs"
        )}
        self.assertTrue({
            "id", "tenant_id", "supply_request_id", "document_fingerprint",
            "pdf_fingerprint", "printer_name", "copies", "idempotency_key",
            "status", "attempt_count", "requested_by_user_id",
        }.issubset(columns))
        indexes = {index["name"] for index in inspector.get_indexes(
            "supply_print_jobs"
        )}
        self.assertIn("uq_supply_print_jobs_normal_fingerprint", indexes)
        unique = {item["name"] for item in inspector.get_unique_constraints(
            "supply_print_jobs"
        )}
        self.assertIn("uq_supply_print_jobs_idempotency_key", unique)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
