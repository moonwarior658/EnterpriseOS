import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0008_add_supply_catalog.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_catalog_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supply catalog migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyCatalogMigrationTests(unittest.TestCase):
    def test_revision_follows_supply_foundation(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0008")
        self.assertEqual(migration.down_revision, "20260727_0007")

    def test_upgrade_creates_catalog_links_and_idempotent_unit_seed(
        self,
    ) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        self.assertEqual(
            [call.args[0] for call in operation.create_table.call_args_list],
            [
                "supply_units",
                "supply_products",
                "supply_product_aliases",
            ],
        )
        added_columns = [
            (call.args[0], call.args[1].name)
            for call in operation.add_column.call_args_list
        ]
        self.assertEqual(
            added_columns,
            [
                ("supply_request_lines", "product_id"),
                ("supply_request_lines", "requested_unit_id"),
                ("supply_request_lines", "quantity"),
            ],
        )
        quantity = operation.add_column.call_args_list[2].args[1]
        self.assertIsInstance(quantity.type, sa.Numeric)
        self.assertEqual(quantity.type.precision, 18)
        self.assertEqual(quantity.type.scale, 3)
        self.assertTrue(quantity.nullable)

        seed_sql = "\n".join(
            str(call.args[0]) for call in operation.execute.call_args_list
        )
        for value in (
            "'KG'",
            "'L'",
            "'PCS'",
            "'PACK'",
            "'BOX'",
            "'кг'",
            "'л'",
            "'шт'",
            "'уп'",
            "'кор'",
        ):
            self.assertIn(value, seed_sql)
        self.assertEqual(seed_sql.count("ON CONFLICT"), 1)

    def test_downgrade_removes_only_catalog_and_nullable_links(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()

        self.assertEqual(
            [call.args[1] for call in operation.drop_column.call_args_list],
            ["quantity", "requested_unit_id", "product_id"],
        )
        self.assertEqual(
            [call.args[0] for call in operation.drop_table.call_args_list],
            [
                "supply_product_aliases",
                "supply_products",
                "supply_units",
            ],
        )
        self.assertNotIn(
            "supply_requests",
            [call.args[0] for call in operation.drop_table.call_args_list],
        )


if __name__ == "__main__":
    unittest.main()
