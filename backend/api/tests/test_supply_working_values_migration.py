import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0016_add_supply_roll_unit.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_working_values_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load working values migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyWorkingValuesMigrationTests(unittest.TestCase):
    def test_revision_follows_unmatched_operations(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0016")
        self.assertEqual(migration.down_revision, "20260727_0015")

    def test_upgrade_adds_only_active_integer_roll_unit(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        sql = str(operation.execute.call_args.args[0])
        self.assertIn("'ROLL', 'рулон', 'рул', false, true", sql)
        self.assertIn("ON CONFLICT (tenant_id, code) DO NOTHING", sql)

    def test_downgrade_removes_only_seeded_roll_unit(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        sql = str(operation.execute.call_args.args[0])
        self.assertIn("tenant_id = 'eclair'", sql)
        self.assertIn("code = 'ROLL'", sql)
        self.assertIn("b20cf0ae-cb8e-4b06-a3ea-a38057a02a06", sql)


if __name__ == "__main__":
    unittest.main()
