import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260729_0018_add_iiko_staging.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_staging_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load iiko migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoMigrationTests(unittest.TestCase):
    def test_revision_follows_current_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260729_0018")
        self.assertEqual(migration.down_revision, "20260728_0017")

    def test_upgrade_creates_isolated_tenant_staging(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        self.assertEqual(
            [call.args[0] for call in operation.create_table.call_args_list],
            ["iiko_sync_runs", "iiko_raw_entities"],
        )
        sync_table = operation.create_table.call_args_list[0]
        sync_column_names = {
            argument.name
            for argument in sync_table.args[1:]
            if hasattr(argument, "name")
        }
        self.assertIn("parameters", sync_column_names)
        raw_table = operation.create_table.call_args_list[1]
        column_names = {
            argument.name
            for argument in raw_table.args[1:]
            if hasattr(argument, "name")
        }
        self.assertTrue(
            {
                "tenant_id",
                "sync_run_id",
                "entity_type",
                "external_id",
                "payload",
                "payload_hash",
                "is_active",
            }
            <= column_names
        )
        constraints = [
            argument
            for argument in raw_table.args
            if argument.__class__.__name__ == "UniqueConstraint"
        ]
        self.assertEqual(len(constraints), 1)
        self.assertEqual(
            constraints[0].name,
            "uq_iiko_raw_entity_version",
        )

    def test_downgrade_removes_only_iiko_tables(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(
            [call.args[0] for call in operation.drop_table.call_args_list],
            ["iiko_raw_entities", "iiko_sync_runs"],
        )
