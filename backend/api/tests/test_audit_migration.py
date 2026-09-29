import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260929_0061_add_immutable_business_audit.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("audit_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load audit migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditMigrationTests(unittest.TestCase):
    def test_revision_constraints_indexes_and_immutability_trigger(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260929_0061")
        self.assertEqual(migration.down_revision, "20260929_0060")
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        table = operation.create_table.call_args
        self.assertEqual(table.args[0], "audit_events")
        names = {
            argument.name
            for argument in table.args[1:]
            if getattr(argument, "name", None)
        }
        self.assertIn("fk_audit_events_correction_tenant", names)
        self.assertIn("ck_audit_events_actor_source", names)
        self.assertEqual(operation.create_index.call_count, 5)
        sql = "\n".join(call.args[0] for call in operation.execute.call_args_list)
        self.assertIn("BEFORE UPDATE OR DELETE", sql)
        self.assertIn("audit_events are immutable", sql)


if __name__ == "__main__":
    unittest.main()
