import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260917_0056_add_iiko_incoming_receipts.py"
)


class IikoIncomingReceiptsMigrationTests(unittest.TestCase):
    def test_revision_and_integrity_contract(self):
        spec = importlib.util.spec_from_file_location("receipt_migration", MIGRATION_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("migration not loadable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.revision, "20260917_0056")
        self.assertEqual(module.down_revision, "20260917_0055")
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for token in (
            "supply_iiko_incoming_receipts",
            "supply_iiko_incoming_receipt_lines",
            "uq_supply_iiko_incoming_receipts_active_acceptance",
            "uq_supply_iiko_incoming_receipts_iiko_document",
            "ck_supply_iiko_incoming_receipts_status",
            "supply_iiko_receipt_line_snapshot_guard",
            "IIKO_RECEIPT_SNAPSHOT_IMMUTABLE",
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
