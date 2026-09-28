import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260928_0058_add_employee_identity_foundation.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("employee_identity_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load employee identity migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EmployeeIdentityMigrationTests(unittest.TestCase):
    def test_revision_follows_current_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260928_0058")
        self.assertEqual(migration.down_revision, "20260925_0057")

    def test_upgrade_defines_identity_tables_and_partial_unique_indexes(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        tables = {call.args[0]: call for call in operation.create_table.call_args_list}
        self.assertEqual(
            set(tables),
            {
                "employees", "employee_role_assignments",
                "employee_department_assignments", "employee_lifecycle_events",
            },
        )
        indexes = {call.args[0]: call for call in operation.create_index.call_args_list}
        self.assertEqual(
            str(indexes["uq_employee_role_assignments_active"].kwargs["postgresql_where"]),
            "valid_to IS NULL",
        )
        self.assertEqual(
            str(indexes["uq_employee_department_assignments_active_primary"].kwargs["postgresql_where"]),
            "valid_to IS NULL AND is_primary",
        )
        self.assertTrue(indexes["uq_employee_role_assignments_active"].kwargs["unique"])
        self.assertTrue(indexes["uq_employee_department_assignments_active_primary"].kwargs["unique"])


if __name__ == "__main__":
    unittest.main()
