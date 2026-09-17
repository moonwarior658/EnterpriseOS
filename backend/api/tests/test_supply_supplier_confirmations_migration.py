import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260917_0046_add_supplier_confirmations.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("supplier_confirmations_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier confirmations migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierConfirmationsMigrationTests(unittest.TestCase):
    def test_revision_follows_email_delivery(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260917_0046")
        self.assertEqual(migration.down_revision, "20260915_0045")

    def test_migration_declares_revision_history_and_tenant_safe_lines(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "supply_supplier_confirmations", "supply_supplier_confirmation_lines",
            "uq_supply_supplier_confirmations_revision", "uq_supply_supplier_confirmations_draft",
            "uq_supply_supplier_confirmations_current",
            "fk_supply_supplier_confirmation_lines_order_line_tenant",
            "fk_supply_supplier_confirmation_lines_unit_tenant",
        ):
            self.assertIn(value, source)


if __name__ == "__main__":
    unittest.main()
