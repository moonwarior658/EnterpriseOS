import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0012_add_public_supply_requests.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "public_supply_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load public supply migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicSupplyMigrationTests(unittest.TestCase):
    def test_revision_follows_request_cycles(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0012")
        self.assertEqual(migration.down_revision, "20260727_0011")

    def test_upgrade_adds_nullable_metadata_and_filtered_token_index(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        columns = {
            call.args[1].name: call.args[1]
            for call in operation.add_column.call_args_list
        }
        self.assertEqual(
            set(columns),
            {
                "public_token_hash",
                "public_token_expires_at",
                "public_author_name",
                "public_author_phone",
                "source_ip_hash",
                "public_created_at",
            },
        )
        self.assertTrue(all(column.nullable for column in columns.values()))
        token_index = operation.create_index.call_args_list[0]
        self.assertEqual(
            token_index.args[:3],
            (
                "uq_supply_requests_public_token_hash",
                "supply_requests",
                ["public_token_hash"],
            ),
        )
        self.assertTrue(token_index.kwargs["unique"])
        self.assertIsInstance(
            token_index.kwargs["postgresql_where"],
            sa.sql.elements.TextClause,
        )

    def test_downgrade_removes_only_public_metadata(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(
            [call.args[1] for call in operation.drop_column.call_args_list],
            [
                "public_created_at",
                "source_ip_hash",
                "public_author_phone",
                "public_author_name",
                "public_token_expires_at",
                "public_token_hash",
            ],
        )


if __name__ == "__main__":
    unittest.main()
