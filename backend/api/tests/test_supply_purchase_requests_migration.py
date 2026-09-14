import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260914_0038_add_supply_purchase_requests.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("purchase_request_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load purchase request migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyPurchaseRequestsMigrationTests(unittest.TestCase):
    def test_revision_follows_current_single_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260914_0038")
        self.assertEqual(migration.down_revision, "20260907_0037")

    def test_sqlite_upgrade_constraints_and_downgrade(self) -> None:
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
        for name in ("supply_units", "supply_products"):
            sa.Table(
                name, metadata,
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
        self.assertTrue({
            "supply_purchase_requests", "supply_purchase_request_lines",
            "supply_purchase_request_line_sources",
        }.issubset(inspector.get_table_names()))
        line_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("supply_purchase_request_lines")
        }
        self.assertIn(
            ("tenant_id", "purchase_request_id", "product_id", "unit_id"),
            line_uniques,
        )
        source_checks = {
            item["name"] for item in inspector.get_check_constraints(
                "supply_purchase_request_line_sources"
            )
        }
        self.assertIn("ck_supply_purchase_request_line_sources_reference", source_checks)
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
        self.assertNotIn("supply_purchase_requests", sa.inspect(engine).get_table_names())
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
