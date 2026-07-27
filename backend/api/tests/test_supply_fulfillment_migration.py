import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0014_add_supply_fulfillment_debts.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_fulfillment_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supply fulfillment migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyFulfillmentMigrationTests(unittest.TestCase):
    def test_revision_follows_planning(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0014")
        self.assertEqual(migration.down_revision, "20260727_0013")

    def test_upgrade_adds_fact_debt_history_and_partial_unique_index(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        created_tables = [
            call.args[0] for call in operation.create_table.call_args_list
        ]
        self.assertEqual(created_tables, [
            "supply_department_debts",
            "supply_department_debt_events",
            "supply_request_line_debt_links",
        ])
        allocation_columns = {
            call.args[1].name: call.args[1]
            for call in operation.add_column.call_args_list
            if call.args[0] == "supply_line_allocations"
        }
        self.assertEqual(set(allocation_columns), {
            "fulfilled_quantity",
            "fulfilled_at",
            "fulfilled_by_user_id",
            "fulfillment_comment",
        })
        self.assertIsInstance(
            allocation_columns["fulfilled_quantity"].type, sa.Numeric
        )
        active_index = next(
            call for call in operation.create_index.call_args_list
            if call.args[0] == "uq_supply_department_debts_active"
        )
        self.assertTrue(active_index.kwargs["unique"])
        self.assertIsInstance(
            active_index.kwargs["postgresql_where"],
            sa.sql.elements.TextClause,
        )

    def test_downgrade_removes_new_objects_in_dependency_order(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(
            [call.args[0] for call in operation.drop_table.call_args_list],
            [
                "supply_request_line_debt_links",
                "supply_department_debt_events",
                "supply_department_debts",
            ],
        )


if __name__ == "__main__":
    unittest.main()
