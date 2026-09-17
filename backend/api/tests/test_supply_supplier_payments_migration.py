import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260917_0052_add_supplier_payments.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("supplier_payments_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier payments migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierPaymentsMigrationTests(unittest.TestCase):
    def test_revision_follows_acceptance_resolutions(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260917_0052")
        self.assertEqual(migration.down_revision, "20260917_0051")

    def test_migration_declares_payment_integrity(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "supply_supplier_payments",
            "payment_due_date",
            "fk_supply_supplier_payments_document_supplier_tenant",
            "fk_supply_supplier_payments_order_supplier_tenant",
            "ck_supply_supplier_payments_amount",
            "ck_supply_supplier_payments_postpayment_document",
            "ck_supply_supplier_payments_order_fields",
            "ck_supply_supplier_payments_recorded",
            "uq_supply_supplier_payments_order_identity",
        ):
            self.assertIn(value, source)


if __name__ == "__main__":
    unittest.main()
