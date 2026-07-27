import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260727_0009_add_supply_line_matching.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_matching_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supply matching migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyMatchingMigrationTests(unittest.TestCase):
    def test_revision_follows_catalog(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260727_0009")
        self.assertEqual(migration.down_revision, "20260727_0008")

    def test_upgrade_adds_nullable_parsed_fields_and_matching_metadata(
        self,
    ) -> None:
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
                "parsed_name",
                "parsed_quantity",
                "parsed_unit_id",
                "match_status",
                "match_method",
                "matched_at",
                "matched_by_user_id",
                "match_confidence",
                "match_notes",
            },
        )
        self.assertIsInstance(columns["parsed_quantity"].type, sa.Numeric)
        self.assertEqual(columns["parsed_quantity"].type.precision, 18)
        self.assertEqual(columns["parsed_quantity"].type.scale, 3)
        self.assertIsInstance(columns["match_confidence"].type, sa.Numeric)
        self.assertEqual(columns["match_confidence"].type.precision, 5)
        self.assertEqual(columns["match_confidence"].type.scale, 4)
        self.assertFalse(columns["match_status"].nullable)
        self.assertIn(
            "UNPROCESSED",
            str(columns["match_status"].server_default.arg),
        )
        foreign_keys = {
            call.args[0]: call.kwargs["ondelete"]
            for call in operation.create_foreign_key.call_args_list
        }
        self.assertEqual(
            foreign_keys,
            {
                "fk_supply_request_lines_parsed_unit_id": "RESTRICT",
                "fk_supply_request_lines_matched_by_user_id": "RESTRICT",
            },
        )

    def test_downgrade_removes_only_matching_fields(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.downgrade()
        self.assertEqual(
            [call.args[1] for call in operation.drop_column.call_args_list],
            [
                "match_notes",
                "match_confidence",
                "matched_by_user_id",
                "matched_at",
                "match_method",
                "match_status",
                "parsed_unit_id",
                "parsed_quantity",
                "parsed_name",
            ],
        )
        operation.drop_table.assert_not_called()


if __name__ == "__main__":
    unittest.main()
