import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260907_0037_add_supply_product_supplier_price_history.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "product_supplier_price_history_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load product supplier price history migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyProductSupplierPriceHistoryMigrationTests(unittest.TestCase):
    def test_revision_follows_current_single_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260907_0037")
        self.assertEqual(migration.down_revision, "20260907_0036")

    def test_sqlite_upgrade_constraints_and_downgrade(self) -> None:
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
        sa.Table(
            "supply_units", metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.UniqueConstraint("tenant_id", "id"),
        )
        sa.Table(
            "supply_product_suppliers", metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.UniqueConstraint("tenant_id", "id"),
        )
        metadata.create_all(engine)
        migration = load_migration()

        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        inspector = sa.inspect(engine)
        table = "supply_product_supplier_price_history"
        self.assertIn(table, inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns(table)}
        self.assertEqual(columns, {
            "id", "tenant_id", "product_supplier_id", "price_per_package",
            "package_quantity", "package_unit_id", "currency",
            "base_unit_price_snapshot", "source", "effective_from",
            "changed_by_user_id", "created_at",
        })
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        self.assertIn("ix_supply_product_supplier_price_history_timeline", indexes)
        checks = {check["name"] for check in inspector.get_check_constraints(table)}
        self.assertEqual(checks, {
            "ck_supply_product_supplier_price_history_base_price",
            "ck_supply_product_supplier_price_history_currency",
            "ck_supply_product_supplier_price_history_price",
            "ck_supply_product_supplier_price_history_quantity",
            "ck_supply_product_supplier_price_history_source",
        })

        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
        self.assertNotIn(table, sa.inspect(engine).get_table_names())
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
