import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260928_0059_add_iiko_employee_links_and_shifts.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("employee_iiko_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load employee iiko migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EmployeeIikoMigrationTests(unittest.TestCase):
    def test_revision_and_identity_constraints(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.down_revision, "20260928_0058")
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        self.assertEqual(
            {call.args[0] for call in operation.create_table.call_args_list},
            {"iiko_employee_links", "employee_iiko_shifts"},
        )
        indexes = {call.args[0]: call for call in operation.create_index.call_args_list}
        self.assertTrue(indexes["uq_iiko_employee_links_active_employee"].kwargs["unique"])
        self.assertTrue(indexes["uq_iiko_employee_links_active_user"].kwargs["unique"])
        self.assertTrue(indexes["uq_employee_iiko_shifts_active_employee"].kwargs["unique"])


if __name__ == "__main__":
    unittest.main()
