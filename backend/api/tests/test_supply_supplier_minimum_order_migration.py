import importlib.util
import unittest
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260914_0042_add_supplier_minimum_order_amount.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supplier_minimum_order_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supplier minimum order migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySupplierMinimumOrderMigrationTests(unittest.TestCase):
    def test_revision_follows_current_single_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260914_0042")
        self.assertEqual(migration.down_revision, "20260914_0041")

    def test_nullable_non_negative_column_and_downgrade(self) -> None:
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        sa.Table(
            "supply_suppliers",
            metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("display_name", sa.String(240), nullable=False),
        )
        metadata.create_all(engine)
        migration = load_migration()

        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        inspector = sa.inspect(engine)
        column = next(
            item for item in inspector.get_columns("supply_suppliers")
            if item["name"] == "minimum_order_amount"
        )
        self.assertTrue(column["nullable"])
        self.assertEqual(column["type"].precision, 18)
        self.assertEqual(column["type"].scale, 2)
        self.assertIn(
            "ck_supply_suppliers_minimum_order_amount",
            {
                item["name"] for item in inspector.get_check_constraints(
                    "supply_suppliers"
                )
            },
        )

        with engine.begin() as connection:
            for amount in (None, "0", "10000.25"):
                connection.execute(
                    sa.text(
                        "INSERT INTO supply_suppliers "
                        "(id, display_name, minimum_order_amount) "
                        "VALUES (:id, :name, :amount)"
                    ),
                    {"id": str(uuid4()), "name": str(amount), "amount": amount},
                )
        with self.assertRaises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO supply_suppliers "
                    "(id, display_name, minimum_order_amount) "
                    "VALUES (:id, 'negative', -0.01)"
                ),
                {"id": str(uuid4())},
            )

        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
        self.assertNotIn(
            "minimum_order_amount",
            {
                item["name"] for item in sa.inspect(engine).get_columns(
                    "supply_suppliers"
                )
            },
        )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
