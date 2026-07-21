import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260721_0002_add_execution_scope_snapshot.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "execution_snapshot_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load execution snapshot migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExecutionSnapshotMigrationTests(unittest.TestCase):
    def test_upgrade_adds_backfills_and_hardens_snapshot_columns(self) -> None:
        migration = load_migration()
        operation = Mock()

        with patch.object(migration, "op", operation):
            migration.upgrade()

        added_names = [
            call.args[1].name for call in operation.add_column.call_args_list
        ]
        self.assertEqual(
            added_names,
            ["scope_type", "scope_id", "recipients"],
        )
        sql = operation.execute.call_args.args[0]
        self.assertIn("FROM automation_schedules", sql)
        self.assertIn("'company'", sql)
        self.assertIn("'[]'::jsonb", sql)
        self.assertEqual(operation.alter_column.call_count, 2)

    def test_downgrade_removes_only_snapshot_columns(self) -> None:
        migration = load_migration()
        operation = Mock()

        with patch.object(migration, "op", operation):
            migration.downgrade()

        dropped = [
            call.args[1] for call in operation.drop_column.call_args_list
        ]
        self.assertEqual(dropped, ["recipients", "scope_id", "scope_type"])


if __name__ == "__main__":
    unittest.main()
