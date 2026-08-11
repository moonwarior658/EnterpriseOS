import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260811_0031_add_iiko_document_expected_payload.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_document_reconciliation_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load reconciliation migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoDocumentReconciliationMigrationTests(unittest.TestCase):
    def test_revision_follows_document_intent_revision(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260811_0031")
        self.assertEqual(migration.down_revision, "20260811_0030")

    def test_upgrade_adds_nullable_expected_payload(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        operation.add_column.assert_called_once()
        table_name, column = operation.add_column.call_args.args
        self.assertEqual(table_name, "iiko_document_writes")
        self.assertEqual(column.name, "expected_payload")
        self.assertTrue(column.nullable)

    def test_downgrade_removes_only_expected_payload(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(operation.method_calls, [
            call.drop_column("iiko_document_writes", "expected_payload")
        ])


if __name__ == "__main__":
    unittest.main()
