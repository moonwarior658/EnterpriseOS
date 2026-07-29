import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/"
    "20260730_0021_add_warehouse_legal_contours.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_warehouse_legal_contour_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load iiko warehouse migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoWarehouseLegalContourMigrationTests(unittest.TestCase):
    def test_revision_follows_source_mapping_migration(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260730_0021")
        self.assertEqual(migration.down_revision, "20260730_0020")

    def test_upgrade_adds_contours_and_removes_source_priority(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        added = [
            (call.args[0], call.args[1].name)
            for call in operation.add_column.call_args_list
        ]
        self.assertEqual(
            added,
            [
                ("departments", "legal_contour"),
                ("iiko_warehouse_mappings", "legal_contour"),
            ],
        )
        self.assertEqual(
            [call.args[1] for call in operation.drop_column.call_args_list],
            ["source_priority", "source_direction"],
        )
        dropped_indexes = {
            call.args[0] for call in operation.drop_index.call_args_list
        }
        self.assertEqual(
            dropped_indexes,
            {"uq_iiko_warehouse_mappings_confirmed_source_priority"},
        )
        statements = [
            str(call.args[0]) for call in operation.execute.call_args_list
        ]
        self.assertTrue(
            any("destination_type = 'SOURCE'" in sql for sql in statements)
        )
        self.assertTrue(
            any("'КУХНЯ'" in sql and "'БАР ГХ'" in sql for sql in statements)
        )
        self.assertFalse(any("'СКЛ'" in sql for sql in statements))


if __name__ == "__main__":
    unittest.main()
