import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0010_complete_supply_product_card.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_product_card_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supply product card migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyProductCardMigrationTests(unittest.TestCase):
    def test_revision_follows_matching(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0010")
        self.assertEqual(migration.down_revision, "20260727_0009")

    def test_upgrade_adds_references_product_fields_and_zone_seed(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        self.assertEqual(
            [call.args[0] for call in operation.create_table.call_args_list],
            ["supply_product_categories", "supply_storage_zones"],
        )
        self.assertEqual(
            [call.args[1].name for call in operation.add_column.call_args_list],
            [
                "iiko_id",
                "category_id",
                "storage_zone_id",
                "archived_at",
                "archived_by_user_id",
            ],
        )
        foreign_keys = {
            call.args[0]: (
                call.args[2],
                call.kwargs["ondelete"],
            )
            for call in operation.create_foreign_key.call_args_list
        }
        self.assertEqual(
            foreign_keys,
            {
                "fk_supply_products_category_id": (
                    "supply_product_categories",
                    "RESTRICT",
                ),
                "fk_supply_products_storage_zone_id": (
                    "supply_storage_zones",
                    "RESTRICT",
                ),
                "fk_supply_products_archived_by_user_id": (
                    "users",
                    "RESTRICT",
                ),
            },
        )
        seed_sql = "\n".join(
            str(call.args[0]) for call in operation.execute.call_args_list
        )
        for code in (
            "FREEZER",
            "REFRIGERATOR",
            "DRY_STORAGE",
            "PACKAGING_STORAGE",
            "HOUSEHOLD_STORAGE",
            "FIXED_ASSETS",
            "OTHER",
        ):
            self.assertIn(code, seed_sql)
        self.assertIn("ON CONFLICT (tenant_id, code) DO NOTHING", seed_sql)
        self.assertTrue(
            any(
                call.args[0] == "uq_supply_products_tenant_iiko_id"
                and call.kwargs["unique"]
                and "postgresql_where" in call.kwargs
                for call in operation.create_index.call_args_list
            )
        )

    def test_downgrade_removes_only_new_product_card_objects(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()

        self.assertEqual(
            [call.args[1] for call in operation.drop_column.call_args_list],
            [
                "archived_by_user_id",
                "archived_at",
                "storage_zone_id",
                "category_id",
                "iiko_id",
            ],
        )
        self.assertEqual(
            [call.args[0] for call in operation.drop_table.call_args_list],
            ["supply_storage_zones", "supply_product_categories"],
        )
        self.assertNotIn(
            "supply_products",
            [call.args[0] for call in operation.drop_table.call_args_list],
        )


if __name__ == "__main__":
    unittest.main()
