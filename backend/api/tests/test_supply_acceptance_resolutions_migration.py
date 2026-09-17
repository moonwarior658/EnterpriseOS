import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260917_0051_add_acceptance_resolutions.py"


class SupplyAcceptanceResolutionsMigrationTests(unittest.TestCase):
    def test_revision_and_required_integrity_contracts(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for token in (
            'revision: str = "20260917_0051"',
            'down_revision: str | None = "20260917_0050"',
            "supply_acceptance_resolutions",
            "uq_supply_acceptance_resolutions_line_issue",
            "fk_supply_acceptance_resolutions_line_acceptance_tenant",
            "ck_supply_acceptance_resolutions_compatible_type",
            "acceptance_resolution_id",
            "uq_supply_procurement_needs_acceptance_resolution",
            "SUPPLIER_SHORTAGE",
            "SUPPLIER_REJECTION",
        ):
            self.assertIn(token, source)

        spec = importlib.util.spec_from_file_location("acceptance_resolutions_migration", MIGRATION_PATH)
        self.assertIsNotNone(spec)


if __name__ == "__main__":
    unittest.main()
