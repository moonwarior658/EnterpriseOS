import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/"
    "20260730_0020_add_iiko_warehouse_destination_type.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_warehouse_destination_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load iiko warehouse migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoWarehouseDestinationMigrationTests(unittest.TestCase):
    def test_revision_follows_explicit_mappings(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260730_0020")
        self.assertEqual(migration.down_revision, "20260729_0019")

    def test_upgrade_preserves_existing_links_as_destination(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        destination_column = operation.add_column.call_args_list[0].args[1]
        self.assertEqual(destination_column.name, "destination_type")
        self.assertFalse(destination_column.nullable)
        self.assertEqual(destination_column.server_default.arg, "DESTINATION")
        self.assertEqual(
            operation.alter_column.call_args.kwargs["server_default"],
            None,
        )

    def test_upgrade_adds_source_constraints_and_unique_priority(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        added_columns = [
            call.args[1].name for call in operation.add_column.call_args_list
        ]
        self.assertEqual(
            added_columns,
            ["destination_type", "source_direction", "source_priority"],
        )
        constraints = {
            call.args[0]
            for call in operation.create_check_constraint.call_args_list
        }
        self.assertEqual(
            constraints,
            {
                "ck_iiko_warehouse_mapping_source_priority_positive",
                "ck_iiko_warehouse_mapping_confirmed_target",
            },
        )
        indexes = {
            call.args[0]: call
            for call in operation.create_index.call_args_list
        }
        source_index = indexes[
            "uq_iiko_warehouse_mappings_confirmed_source_priority"
        ]
        self.assertEqual(
            source_index.args[2],
            ["tenant_id", "source_direction", "source_priority"],
        )
        self.assertTrue(source_index.kwargs["unique"])

    def test_downgrade_removes_only_new_warehouse_fields(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(
            [call.args[1] for call in operation.drop_column.call_args_list],
            ["source_priority", "source_direction", "destination_type"],
        )
