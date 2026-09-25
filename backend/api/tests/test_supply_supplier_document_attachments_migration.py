import importlib.util
import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260925_0057_add_supplier_document_attachments.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supplier_document_attachments_migration", MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier document attachments migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierDocumentAttachmentsMigrationTests(unittest.TestCase):
    def test_revision_follows_iiko_receipts(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260925_0057")
        self.assertEqual(migration.down_revision, "20260917_0056")

    def test_migration_declares_attachment_integrity(self) -> None:
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for value in (
            "supply_supplier_document_attachments",
            "fk_supply_supplier_document_attachments_document_tenant",
            "ck_supply_supplier_document_attachments_content_type",
            "ck_supply_supplier_document_attachments_size",
            "ix_supply_supplier_document_attachments_document",
        ):
            self.assertIn(value, source)


if __name__ == "__main__":
    unittest.main()
