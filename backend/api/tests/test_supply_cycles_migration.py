import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0011_add_supply_request_cycles.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_cycles_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supply cycles migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyCyclesMigrationTests(unittest.TestCase):
    def test_revision_follows_product_card(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0011")
        self.assertEqual(migration.down_revision, "20260727_0010")

    def test_upgrade_adds_cycle_request_link_and_duplicate_metadata(
        self,
    ) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        cycle_call = operation.create_table.call_args_list[0]
        self.assertEqual(cycle_call.args[0], "supply_request_cycles")
        cycle_columns = {
            item.name: item
            for item in cycle_call.args[1:]
            if isinstance(item, sa.Column)
        }
        self.assertEqual(
            set(cycle_columns),
            {
                "id",
                "tenant_id",
                "direction_id",
                "cycle_date",
                "opens_at",
                "closes_at",
                "hard_closes_at",
                "status",
                "created_at",
                "updated_at",
            },
        )
        self.assertIsInstance(cycle_columns["cycle_date"].type, sa.Date)
        self.assertTrue(cycle_columns["opens_at"].type.timezone)
        self.assertTrue(cycle_columns["closes_at"].type.timezone)
        self.assertTrue(cycle_columns["hard_closes_at"].nullable)

        added_columns = [
            (call.args[0], call.args[1].name, call.args[1].nullable)
            for call in operation.add_column.call_args_list
        ]
        self.assertEqual(
            added_columns,
            [
                ("supply_requests", "cycle_id", True),
                ("supply_request_lines", "duplicate_group_id", True),
                ("supply_request_lines", "duplicate_status", False),
            ],
        )
        operation.create_unique_constraint.assert_called_once_with(
            "uq_supply_requests_tenant_department_direction_cycle",
            "supply_requests",
            ["tenant_id", "department_id", "direction_id", "cycle_id"],
        )
        operation.create_foreign_key.assert_called_once_with(
            "fk_supply_requests_cycle_id",
            "supply_requests",
            "supply_request_cycles",
            ["cycle_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    def test_downgrade_removes_only_new_objects_in_dependency_order(
        self,
    ) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()

        self.assertEqual(
            [call.args[1] for call in operation.drop_column.call_args_list],
            ["duplicate_status", "duplicate_group_id", "cycle_id"],
        )
        operation.drop_table.assert_called_once_with("supply_request_cycles")


if __name__ == "__main__":
    unittest.main()
