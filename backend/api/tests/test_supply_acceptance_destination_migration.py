import importlib.util
import unittest
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260917_0050_add_acceptance_destination.py"
)


class SupplyAcceptanceDestinationMigrationTests(unittest.TestCase):
    def test_revision_and_tenant_safe_destination_contract(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "acceptance_destination_migration", MIGRATION_PATH
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("migration not loadable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.revision, "20260917_0050")
        self.assertEqual(module.down_revision, "20260917_0049")
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "destination_mapping_id",
            "fk_supply_supplier_acceptances_destination_tenant",
            "iiko_warehouse_mappings",
            "ix_supply_supplier_acceptances_destination",
        ):
            self.assertIn(value, source)


if __name__ == "__main__":
    unittest.main()
