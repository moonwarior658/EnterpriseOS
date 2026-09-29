import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260929_0060_add_shift_department_confirmations.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("action_context_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load action context migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ActionContextMigrationTests(unittest.TestCase):
    def test_revision_and_confirmation_constraints(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260929_0060")
        self.assertEqual(migration.down_revision, "20260928_0059")
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        operation.create_unique_constraint.assert_called_once_with(
            "uq_employee_iiko_shifts_tenant_id",
            "employee_iiko_shifts",
            ["tenant_id", "id"],
        )
        table = operation.create_table.call_args
        self.assertEqual(table.args[0], "shift_department_confirmations")
        constraint_names = {
            argument.name
            for argument in table.args[1:]
            if getattr(argument, "name", None)
        }
        self.assertIn(
            "uq_shift_department_confirmations_shift_employee",
            constraint_names,
        )


if __name__ == "__main__":
    unittest.main()
