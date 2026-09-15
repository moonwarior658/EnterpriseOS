import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260915_0045_add_supplier_order_email_delivery.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("supplier_order_email_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier order email migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierOrderEmailMigrationTests(unittest.TestCase):
    def test_revision_follows_message_preparation(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260915_0045")
        self.assertEqual(migration.down_revision, "20260915_0044")

    def test_migration_declares_delivery_history_and_sent_state(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "supply_supplier_order_delivery_attempts",
            "sent_at",
            "automation_execution_id",
            "idempotency_key",
            "ck_supply_supplier_order_delivery_attempts_timestamps",
            "uq_supply_supplier_order_delivery_attempts_active",
            "fk_supply_supplier_order_delivery_attempts_order_tenant",
        ):
            self.assertIn(value, source)


if __name__ == "__main__":
    unittest.main()
