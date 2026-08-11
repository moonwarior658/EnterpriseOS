import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260811_0030_add_iiko_document_writes.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_document_write_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load iiko document write migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoDocumentWriteMigrationTests(unittest.TestCase):
    def test_revision_follows_current_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260811_0030")
        self.assertEqual(migration.down_revision, "20260806_0029")

    def test_upgrade_creates_exact_intent_constraints(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        operation.create_table.assert_called_once()
        table_call = operation.create_table.call_args
        self.assertEqual(table_call.args[0], "iiko_document_writes")
        columns = {
            argument.name: argument
            for argument in table_call.args[1:]
            if argument.__class__.__name__ == "Column"
        }
        self.assertEqual(
            set(columns),
            {
                "id",
                "supply_request_id",
                "source_store_id",
                "document_type",
                "iiko_document_id",
                "iiko_document_number",
                "status",
                "payload_hash",
                "created_at",
                "updated_at",
                "last_error",
            },
        )
        self.assertTrue(columns["iiko_document_number"].nullable)
        self.assertTrue(columns["last_error"].nullable)

        unique_constraints = {
            argument.name: tuple(argument._pending_colargs)
            for argument in table_call.args
            if argument.__class__.__name__ == "UniqueConstraint"
        }
        self.assertEqual(unique_constraints, {
            "uq_iiko_document_writes_request_source_type": (
                "supply_request_id",
                "source_store_id",
                "document_type",
            ),
            "uq_iiko_document_writes_iiko_document_id": (
                "iiko_document_id",
            ),
        })

    def test_downgrade_removes_only_document_write_table(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(operation.method_calls, [
            call.drop_index(
                "ix_iiko_document_writes_status_updated",
                table_name="iiko_document_writes",
            ),
            call.drop_table("iiko_document_writes"),
        ])


if __name__ == "__main__":
    unittest.main()
