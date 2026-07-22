import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260722_0004_add_automation_runtime_status.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "runtime_status_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load runtime status migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeStatusMigrationTests(unittest.TestCase):
    def test_upgrade_creates_single_keyed_runtime_table(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        args = operation.create_table.call_args.args
        self.assertEqual(args[0], "automation_runtime_status")
        column_names = [item.name for item in args[1:] if hasattr(item, "name")]
        self.assertIn("component_key", column_names)
        self.assertNotIn("payload", column_names)

    def test_downgrade_drops_only_runtime_table(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        operation.drop_table.assert_called_once_with("automation_runtime_status")


if __name__ == "__main__":
    unittest.main()
