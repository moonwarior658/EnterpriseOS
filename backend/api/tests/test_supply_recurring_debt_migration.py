import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260802_0023_stabilize_supply_recurring_debts.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_recurring_debt_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load recurring debt migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyRecurringDebtMigrationTests(unittest.TestCase):
    def test_migration_preserves_cycle_count_and_last_cycle_id(self) -> None:
        migration = load_migration()
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE supply_department_debts (
                    id TEXT PRIMARY KEY,
                    cycle_count INTEGER NOT NULL,
                    last_cycle_id TEXT
                )
            """))
            connection.execute(
                text("""
                    INSERT INTO supply_department_debts
                        (id, cycle_count, last_cycle_id)
                    VALUES ('debt-1', 4, 'cycle-4')
                """)
            )
            operations = Operations(MigrationContext.configure(connection))
            original_op = migration.op
            migration.op = operations
            try:
                migration.upgrade()
                migration.downgrade()
            finally:
                migration.op = original_op
            row = connection.execute(text("""
                SELECT cycle_count, last_cycle_id
                FROM supply_department_debts
                WHERE id = 'debt-1'
            """)).one()

        self.assertEqual(row.cycle_count, 4)
        self.assertEqual(row.last_cycle_id, "cycle-4")


if __name__ == "__main__":
    unittest.main()
