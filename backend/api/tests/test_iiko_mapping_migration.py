import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260729_0019_add_iiko_mappings.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_mapping_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load iiko mapping migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoMappingMigrationTests(unittest.TestCase):
    def test_revision_follows_iiko_staging(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260729_0019")
        self.assertEqual(migration.down_revision, "20260729_0018")

    def test_upgrade_creates_mapping_and_audit_tables(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        self.assertEqual(
            [call.args[0] for call in operation.create_table.call_args_list],
            [
                "iiko_product_mappings",
                "iiko_unit_mappings",
                "iiko_warehouse_mappings",
                "iiko_mapping_audit_events",
            ],
        )
        index_names = {
            call.args[0] for call in operation.create_index.call_args_list
        }
        self.assertIn(
            "uq_iiko_product_mappings_confirmed_eos",
            index_names,
        )
        self.assertIn(
            "uq_iiko_warehouse_mappings_confirmed_role",
            index_names,
        )

    def test_downgrade_preserves_staging_tables(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(
            [call.args[0] for call in operation.drop_table.call_args_list],
            [
                "iiko_mapping_audit_events",
                "iiko_warehouse_mappings",
                "iiko_unit_mappings",
                "iiko_product_mappings",
            ],
        )
