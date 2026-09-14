import importlib.util
import unittest
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20260914_0040_collect_procurement_needs.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("collector_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load collector migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplyPurchaseRequestCollectorMigrationTests(unittest.TestCase):
    def test_revision_follows_procurement_need_foundation(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260914_0040")
        self.assertEqual(migration.down_revision, "20260914_0039")

    def test_manual_survives_and_new_source_contract_is_enforced(self) -> None:
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        lines = sa.Table(
            "supply_purchase_request_lines", metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("manual_future_quantity", sa.Numeric(18, 3), nullable=False),
            sa.UniqueConstraint("tenant_id", "id"),
            sa.CheckConstraint(
                "manual_future_quantity > 0",
                name="ck_supply_purchase_request_lines_manual_future_quantity",
            ),
        )
        needs = sa.Table(
            "supply_procurement_needs", metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("source_type", sa.String(24), nullable=False),
            sa.UniqueConstraint("tenant_id", "id"),
        )
        sources = sa.Table(
            "supply_purchase_request_line_sources", metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("purchase_request_line_id", sa.Uuid(), nullable=False),
            sa.Column("source_type", sa.String(32), nullable=False),
            sa.Column("source_id", sa.Uuid(), nullable=True),
            sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
            sa.Column("unit_id", sa.Uuid(), nullable=False),
            sa.CheckConstraint(
                "source_type IN ('SUPPLY_REQUEST', 'DEPARTMENT_DEBT', 'MANUAL_FUTURE')",
                name="ck_supply_purchase_request_line_sources_type",
            ),
            sa.CheckConstraint(
                "(source_type = 'MANUAL_FUTURE' AND source_id IS NULL) OR "
                "(source_type <> 'MANUAL_FUTURE' AND source_id IS NOT NULL)",
                name="ck_supply_purchase_request_line_sources_reference",
            ),
        )
        metadata.create_all(engine)
        line_id, source_id, unit_id = uuid4(), uuid4(), uuid4()
        with engine.begin() as connection:
            connection.execute(lines.insert(), {
                "id": line_id, "tenant_id": "tenant-a", "manual_future_quantity": 5,
            })
            connection.execute(sources.insert(), {
                "id": source_id, "tenant_id": "tenant-a",
                "purchase_request_line_id": line_id,
                "source_type": "MANUAL_FUTURE", "source_id": None,
                "quantity": 5, "unit_id": unit_id,
            })
            migration = load_migration()
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        inspector = sa.inspect(engine)
        source_columns = {column["name"] for column in inspector.get_columns(sources.name)}
        self.assertIn("procurement_need_id", source_columns)
        self.assertNotIn("source_id", source_columns)
        self.assertIn(
            "fk_supply_purchase_request_line_sources_need_tenant",
            {fk["name"] for fk in inspector.get_foreign_keys(sources.name)},
        )
        self.assertIn(
            "uq_supply_purchase_request_line_sources_need",
            {index["name"] for index in inspector.get_indexes(sources.name)},
        )
        with engine.connect() as connection:
            row = connection.execute(sa.text(
                "SELECT source_type, procurement_need_id, quantity "
                "FROM supply_purchase_request_line_sources"
            )).one()
            self.assertEqual(tuple(row), ("MANUAL_FUTURE", None, 5))

        need_id = uuid4()
        with engine.begin() as connection:
            connection.execute(needs.insert(), {
                "id": need_id, "tenant_id": "tenant-a", "source_type": "REQUEST_LINE",
            })
            connection.execute(sa.text(
                "INSERT INTO supply_purchase_request_line_sources "
                "(id, tenant_id, purchase_request_line_id, source_type, "
                "procurement_need_id, quantity, unit_id) "
                "VALUES (:id, 'tenant-a', :line_id, 'PROCUREMENT_NEED', "
                ":need_id, 1, :unit_id)"
            ), {"id": uuid4().hex, "line_id": line_id.hex, "need_id": need_id.hex, "unit_id": unit_id.hex})
        with self.assertRaises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(sa.text(
                "INSERT INTO supply_purchase_request_line_sources "
                "(id, tenant_id, purchase_request_line_id, source_type, "
                "procurement_need_id, quantity, unit_id) "
                "VALUES (:id, 'tenant-a', :line_id, 'PROCUREMENT_NEED', "
                ":need_id, 1, :unit_id)"
            ), {"id": uuid4().hex, "line_id": line_id.hex, "need_id": need_id.hex, "unit_id": unit_id.hex})

        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
        source_columns = {
            column["name"] for column in sa.inspect(engine).get_columns(sources.name)
        }
        self.assertIn("source_id", source_columns)
        self.assertNotIn("procurement_need_id", source_columns)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
