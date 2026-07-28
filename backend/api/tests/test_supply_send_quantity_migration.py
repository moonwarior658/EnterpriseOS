import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260728_0017_add_supply_send_quantity.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_send_quantity_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load send quantity migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySendQuantityMigrationTests(unittest.TestCase):
    def test_revision_follows_roll_unit(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260728_0017")
        self.assertEqual(migration.down_revision, "20260727_0016")

    def test_upgrade_adds_nullable_nonnegative_send_quantity(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        columns = [
            item.args[1]
            for item in operation.add_column.call_args_list
        ]
        self.assertEqual(
            [column.name for column in columns],
            ["working_name_override", "send_quantity"],
        )
        self.assertTrue(all(column.nullable for column in columns))
        operation.create_check_constraint.assert_called_once_with(
            "ck_supply_request_lines_send_quantity_nonnegative",
            "supply_request_lines",
            "send_quantity IS NULL OR send_quantity >= 0",
        )

    def test_downgrade_removes_only_send_quantity(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(
            operation.method_calls,
            [
                call.drop_constraint(
                    "ck_supply_request_lines_send_quantity_nonnegative",
                    "supply_request_lines",
                    type_="check",
                ),
                call.drop_column("supply_request_lines", "send_quantity"),
                call.drop_column(
                    "supply_request_lines",
                    "working_name_override",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
