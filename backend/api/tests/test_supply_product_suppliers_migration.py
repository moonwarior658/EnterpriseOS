import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260907_0036_add_supply_product_suppliers.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("product_suppliers_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load product suppliers migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyProductSuppliersMigrationTests(unittest.TestCase):
    def test_revision_follows_supplier_foundation(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260907_0036")
        self.assertEqual(migration.down_revision, "20260907_0035")

    def test_upgrade_defines_partial_unique_indexes(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()
        indexes = {call.args[0]: call for call in operation.create_index.call_args_list}
        pair = indexes["uq_supply_product_suppliers_active_pair"]
        primary = indexes["uq_supply_product_suppliers_active_primary"]
        self.assertTrue(pair.kwargs["unique"])
        self.assertEqual(str(pair.kwargs["postgresql_where"]), "is_active = true")
        self.assertTrue(primary.kwargs["unique"])
        self.assertEqual(
            str(primary.kwargs["postgresql_where"]),
            "is_active = true AND role = 'PRIMARY'",
        )

    def test_sqlite_upgrade_and_downgrade(self) -> None:
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
        for name in ("supply_units", "supply_products", "supply_suppliers"):
            sa.Table(
                name,
                metadata,
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
        self.assertIn("supply_product_suppliers", inspector.get_table_names())
        indexes = {item["name"]: item for item in inspector.get_indexes("supply_product_suppliers")}
        self.assertTrue(indexes["uq_supply_product_suppliers_active_pair"]["unique"])
        self.assertTrue(indexes["uq_supply_product_suppliers_active_primary"]["unique"])
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
        self.assertNotIn("supply_product_suppliers", sa.inspect(engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
