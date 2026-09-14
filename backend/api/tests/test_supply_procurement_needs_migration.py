import importlib.util
import unittest
from pathlib import Path

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260914_0039_add_supply_procurement_needs.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "procurement_need_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load procurement need migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOperations:
    def __init__(self) -> None:
        self.tables = {}
        self.indexes = {}
        self.added_columns = []
        self.unique_constraints = []
        self.dropped = []

    def add_column(self, table_name, column):
        self.added_columns.append((table_name, column))

    def create_unique_constraint(self, name, table_name, columns):
        self.unique_constraints.append((name, table_name, tuple(columns)))

    def create_table(self, name, *elements):
        self.tables[name] = elements

    def create_index(self, name, table_name, columns, **kwargs):
        self.indexes[name] = (table_name, tuple(columns), kwargs)

    def drop_index(self, name, **kwargs):
        self.dropped.append(("index", name))

    def drop_table(self, name):
        self.dropped.append(("table", name))

    def drop_constraint(self, name, table_name, **kwargs):
        self.dropped.append(("constraint", name))

    def drop_column(self, table_name, column_name):
        self.dropped.append(("column", table_name, column_name))


class SupplyProcurementNeedsMigrationTests(unittest.TestCase):
    def test_revision_and_schema_contract(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260914_0039")
        self.assertEqual(migration.down_revision, "20260914_0038")
        recorder = RecordingOperations()
        migration.op = recorder
        migration.upgrade()

        self.assertEqual(
            [(name, column.name, column.nullable) for name, column in recorder.added_columns],
            [("supply_requests", "need_date", True)],
        )
        self.assertIn("supply_procurement_needs", recorder.tables)
        elements = recorder.tables["supply_procurement_needs"]
        columns = {item.name: item for item in elements if isinstance(item, sa.Column)}
        self.assertTrue({
            "id", "tenant_id", "source_type", "supply_request_line_id",
            "department_debt_id", "basis_stock_calculation_line_id",
            "product_id", "unit_id", "quantity", "need_date", "status",
            "reason", "version", "reserved_purchase_request_id", "created_at",
            "updated_at", "closed_at",
        }.issubset(columns))
        checks = {
            item.name for item in elements if isinstance(item, sa.CheckConstraint)
        }
        self.assertTrue({
            "ck_supply_procurement_needs_source",
            "ck_supply_procurement_needs_quantity",
            "ck_supply_procurement_needs_version",
            "ck_supply_procurement_needs_closed_state",
        }.issubset(checks))
        self.assertTrue({
            "uq_supply_procurement_needs_open_request_line",
            "uq_supply_procurement_needs_open_debt",
            "ix_supply_procurement_needs_tenant_status_date_product_unit",
        }.issubset(recorder.indexes))

        migration.downgrade()
        self.assertIn(("table", "supply_procurement_needs"), recorder.dropped)
        self.assertIn(
            ("column", "supply_requests", "need_date"), recorder.dropped
        )


if __name__ == "__main__":
    unittest.main()
