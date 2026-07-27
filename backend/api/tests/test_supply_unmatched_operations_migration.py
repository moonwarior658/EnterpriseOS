import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0015_allow_unmatched_supply_operations.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_unmatched_operations_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load unmatched operations migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyUnmatchedOperationsMigrationTests(unittest.TestCase):
    def test_revision_follows_fulfillment(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0015")
        self.assertEqual(migration.down_revision, "20260727_0014")

    def test_upgrade_backfills_name_and_allows_null_product(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        added = operation.add_column.call_args.args[1]
        self.assertEqual(added.name, "working_name")
        self.assertIsInstance(added.type, sa.Text)
        self.assertTrue(added.nullable)
        self.assertEqual(operation.execute.call_count, 1)
        alterations = {
            call.args[1]: call.kwargs["nullable"]
            for call in operation.alter_column.call_args_list
        }
        self.assertEqual(
            alterations,
            {"working_name": False, "product_id": True},
        )

    def test_downgrade_refuses_data_loss_and_restores_schema(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(operation.execute.call_count, 1)
        operation.alter_column.assert_called_once_with(
            "supply_department_debts",
            "product_id",
            existing_type=unittest.mock.ANY,
            nullable=False,
        )
        operation.drop_column.assert_called_once_with(
            "supply_department_debts",
            "working_name",
        )


if __name__ == "__main__":
    unittest.main()
