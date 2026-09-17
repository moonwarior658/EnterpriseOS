import importlib.util
import unittest
from pathlib import Path

MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260917_0049_add_supplier_acceptances.py"


class SupplySupplierAcceptancesMigrationTests(unittest.TestCase):
    def test_revision_and_integrity_contract(self) -> None:
        spec = importlib.util.spec_from_file_location("supplier_acceptances_migration", MIGRATION_PATH)
        if spec is None or spec.loader is None: raise RuntimeError("migration not loadable")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(module.revision, "20260917_0049")
        self.assertEqual(module.down_revision, "20260917_0048")
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "supply_supplier_acceptances", "supply_supplier_acceptance_lines",
            "fk_supply_supplier_acceptances_document_order_tenant",
            "fk_supply_supplier_acceptance_lines_document_line_tenant",
            "ck_supply_supplier_acceptance_lines_equation",
            "ck_supply_supplier_acceptance_lines_rejection",
            "uq_supply_supplier_acceptance_lines_document_identity",
        ):
            self.assertIn(value, source)


if __name__ == "__main__": unittest.main()
