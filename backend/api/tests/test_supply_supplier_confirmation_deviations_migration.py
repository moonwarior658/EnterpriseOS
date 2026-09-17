import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260917_0047_add_supplier_confirmation_deviations.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("supplier_confirmation_deviations_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier confirmation deviations migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierConfirmationDeviationsMigrationTests(unittest.TestCase):
    def test_revision_follows_supplier_confirmations(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260917_0047")
        self.assertEqual(migration.down_revision, "20260917_0046")

    def test_migration_declares_constraints_and_tenant_safe_foreign_keys(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "supply_supplier_confirmation_deviations",
            "ck_supply_confirmation_deviations_decision_consistency",
            "uq_supply_confirmation_deviations_line_type",
            "uq_supply_confirmation_deviations_header_type",
            "fk_supply_confirmation_deviations_confirmation_tenant",
            "fk_supply_confirmation_deviations_line_tenant",
            "fk_supply_confirmation_deviations_order_line_tenant",
        ):
            self.assertIn(value, source)


if __name__ == "__main__":
    unittest.main()
