import importlib.util
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260929_0062_correct_iiko_personal_shift_contract.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_personal_shift_contract_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load iiko personal shift contract migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoPersonalShiftContractMigrationTests(unittest.TestCase):
    def test_revision_mapping_and_reconciliation_column(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260929_0062")
        self.assertEqual(migration.down_revision, "20260929_0061")
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        table = operation.create_table.call_args
        self.assertEqual(table.args[0], "iiko_department_mappings")
        names = {
            argument.name
            for argument in table.args[1:]
            if getattr(argument, "name", None)
        }
        self.assertIn("uq_iiko_department_mappings_tenant_external", names)
        self.assertIn("fk_iiko_department_mappings_department_tenant", names)
        operation.alter_column.assert_called_once_with(
            "employee_iiko_shifts",
            "raw_external_idempotency_key",
            new_column_name="reconciliation_key",
            existing_type=ANY,
            existing_nullable=False,
        )
        operation.create_unique_constraint.assert_called_once_with(
            "uq_employee_iiko_shifts_reconciliation",
            "employee_iiko_shifts",
            ["tenant_id", "reconciliation_key"],
        )


if __name__ == "__main__":
    unittest.main()
