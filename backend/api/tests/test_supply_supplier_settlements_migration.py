import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260917_0053_add_supplier_settlements.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("supplier_settlements_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier settlements migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierSettlementsMigrationTests(unittest.TestCase):
    def test_revision_and_schema_contract(self):
        migration = load_migration()
        self.assertEqual(migration.revision, "20260917_0053")
        self.assertEqual(migration.down_revision, "20260917_0052")
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "supply_supplier_obligations", "financial_role",
            "uq_supply_supplier_documents_active_payable_obligation",
            "supply_supplier_payment_allocations", "supply_supplier_settlement_adjustments",
            "Ambiguous legacy payable supplier documents",
            "Recorded payments linked to non-payable legacy documents",
        ):
            self.assertIn(value, source)

    def test_preflight_stops_ambiguous_invoice_and_upd(self):
        migration = load_migration()
        connection = Mock()
        connection.execute.return_value.mappings.return_value.all.return_value = [{
            "tenant_id": "t", "supplier_order_id": "order", "supplier": "Supplier",
            "documents": "invoice:INVOICE:1, upd:UPD:2",
        }]
        with self.assertRaisesRegex(RuntimeError, "Ambiguous legacy"):
            migration._preflight(connection)

    def test_preflight_stops_payment_linked_to_delivery_note(self):
        migration = load_migration()
        first = Mock(); first.mappings.return_value.all.return_value = []
        second = Mock(); second.mappings.return_value.all.return_value = [{
            "payment_id": "payment", "supplier_document_id": "document",
            "document_type": "DELIVERY_NOTE", "document_number": "DN-1",
        }]
        connection = Mock(); connection.execute.side_effect = [first, second]
        with self.assertRaisesRegex(RuntimeError, "non-payable legacy"):
            migration._preflight(connection)

    def test_preflight_stops_multiple_invoices(self):
        migration = load_migration()
        connection = Mock()
        connection.execute.return_value.mappings.return_value.all.return_value = [{
            "tenant_id": "t", "supplier_order_id": "order", "supplier": "Supplier",
            "documents": "invoice-1:INVOICE:1, invoice-2:INVOICE:2",
        }]
        with self.assertRaisesRegex(RuntimeError, "Ambiguous legacy"):
            migration._preflight(connection)


if __name__ == "__main__":
    unittest.main()
