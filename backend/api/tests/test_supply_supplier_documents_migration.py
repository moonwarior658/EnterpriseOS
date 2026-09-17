import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260917_0048_add_supplier_documents.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("supplier_documents_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier documents migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierDocumentsMigrationTests(unittest.TestCase):
    def test_revision_follows_confirmation_deviations(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260917_0048")
        self.assertEqual(migration.down_revision, "20260917_0047")

    def test_migration_declares_document_integrity(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "supply_supplier_documents",
            "supply_supplier_document_lines",
            "uq_supply_supplier_documents_identity",
            "fk_supply_supplier_documents_confirmation_order_tenant",
            "fk_supply_supplier_document_lines_document_order_tenant",
            "fk_supply_supplier_document_lines_confirmation_line_tenant",
            "fk_supply_supplier_document_lines_unit_tenant",
            "ck_supply_supplier_document_lines_pricing_fields",
            "ck_supply_supplier_documents_recorded",
        ):
            self.assertIn(value, source)


if __name__ == "__main__":
    unittest.main()
