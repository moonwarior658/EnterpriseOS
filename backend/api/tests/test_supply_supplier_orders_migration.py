import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260915_0043_add_supply_supplier_orders.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("supplier_orders_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier orders migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierOrdersMigrationTests(unittest.TestCase):
    def test_revision_follows_current_single_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260915_0043")
        self.assertEqual(migration.down_revision, "20260914_0042")

    def test_migration_declares_snapshot_and_active_ownership(self) -> None:
        source = MIGRATION_PATH.read_text()
        self.assertIn('"supply_supplier_orders"', source)
        self.assertIn('"supply_supplier_order_lines"', source)
        self.assertIn('"product_name_snapshot"', source)
        self.assertIn('"is_active_owner"', source)
        self.assertIn('"uq_supply_supplier_order_lines_active_allocation"', source)
        self.assertIn('postgresql_where=sa.text("is_active_owner = true")', source)


if __name__ == "__main__":
    unittest.main()
