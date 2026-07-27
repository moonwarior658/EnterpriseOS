import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0007_add_supply_requests.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_request_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supply request migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyMigrationTests(unittest.TestCase):
    def test_revision_follows_current_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0007")
        self.assertEqual(migration.down_revision, "20260726_0006")

    def test_upgrade_creates_only_supply_tables_and_exact_seed(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        created_tables = [
            call.args[0] for call in operation.create_table.call_args_list
        ]
        self.assertEqual(
            created_tables,
            [
                "departments",
                "supply_request_directions",
                "supply_requests",
                "supply_request_lines",
            ],
        )
        seed_sql = "\n".join(
            str(call.args[0]) for call in operation.execute.call_args_list
        )
        for value in (
            "М15",
            "Матросова 15",
            "М35",
            "Матросова 35",
            "М6А",
            "Маяковского 6а",
            "ЦЕХ",
            "Цех производство",
            "ATO",
            "Авто",
            "MAIN",
            "Основной",
            "HOUSEHOLD",
            "Хозяйственный",
        ):
            self.assertIn(value, seed_sql)
        for forbidden in ("KITCHEN", "WORKSHOP_GH", "BAR_GH", "'СКЛ'"):
            self.assertNotIn(forbidden, seed_sql)
        self.assertEqual(seed_sql.count("ON CONFLICT"), 2)
        self.assertNotIn("work_requests", seed_sql)

        supply_table_args = next(
            call.args[1:]
            for call in operation.create_table.call_args_list
            if call.args[0] == "supply_requests"
        )
        columns = {
            item.name: item
            for item in supply_table_args
            if isinstance(item, sa.Column)
        }
        self.assertIsInstance(columns["created_by_user_id"].type, sa.Integer)
        self.assertIsInstance(
            columns["source_work_request_id"].type,
            sa.Integer,
        )
        foreign_keys = {
            (
                tuple(item.column_keys),
                tuple(element.target_fullname for element in item.elements),
                item.ondelete,
            )
            for item in supply_table_args
            if isinstance(item, sa.ForeignKeyConstraint)
        }
        self.assertIn(
            (("created_by_user_id",), ("users.id",), "RESTRICT"),
            foreign_keys,
        )
        self.assertIn(
            (
                ("source_work_request_id",),
                ("work_requests.id",),
                "RESTRICT",
            ),
            foreign_keys,
        )

    def test_downgrade_drops_only_new_tables_in_dependency_order(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()

        dropped_tables = [
            call.args[0] for call in operation.drop_table.call_args_list
        ]
        self.assertEqual(
            dropped_tables,
            [
                "supply_request_lines",
                "supply_requests",
                "supply_request_directions",
                "departments",
            ],
        )


if __name__ == "__main__":
    unittest.main()
