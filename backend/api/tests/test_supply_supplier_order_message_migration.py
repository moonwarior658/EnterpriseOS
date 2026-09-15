import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260915_0044_add_supplier_order_communication_snapshot.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("supplier_order_message_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier order message migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierOrderMessageMigrationTests(unittest.TestCase):
    def test_revision_follows_supplier_order_foundation(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260915_0044")
        self.assertEqual(migration.down_revision, "20260915_0043")

    def test_migration_declares_atomic_communication_snapshot(self) -> None:
        source = MIGRATION_PATH.read_text()
        for column in (
            "recipient_email_snapshot", "recipient_name_snapshot",
            "responsible_name_snapshot", "responsible_phone_snapshot",
        ):
            self.assertIn(f'"{column}"', source)
        self.assertIn('"ck_supply_supplier_orders_communication_snapshot"', source)


if __name__ == "__main__":
    unittest.main()
