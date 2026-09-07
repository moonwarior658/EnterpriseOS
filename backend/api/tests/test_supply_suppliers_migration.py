import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260907_0035_add_supply_suppliers.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "supply_suppliers_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load supply suppliers migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupplySuppliersMigrationTests(unittest.TestCase):
    def test_revision_follows_current_head(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260907_0035")
        self.assertEqual(migration.down_revision, "20260824_0034")

    def test_upgrade_defines_postgresql_active_inn_unique_index(self) -> None:
        migration = load_migration()
        operation = Mock()
        with patch.object(migration, "op", operation):
            migration.upgrade()

        index_call = next(
            call
            for call in operation.create_index.call_args_list
            if call.args[0] == "uq_supply_suppliers_tenant_active_inn"
        )
        self.assertTrue(index_call.kwargs["unique"])
        self.assertEqual(
            str(index_call.kwargs["postgresql_where"]),
            "inn IS NOT NULL AND is_active = true",
        )

    def test_upgrade_and_downgrade_create_guarded_supplier_table(self) -> None:
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        sa.Table(
            "users",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
        )
        metadata.create_all(engine)

        with engine.begin() as connection:
            migration = load_migration()
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        inspector = sa.inspect(engine)
        columns = {
            column["name"]
            for column in inspector.get_columns("supply_suppliers")
        }
        self.assertEqual(
            columns,
            {
                "id", "tenant_id", "display_name", "legal_name", "inn",
                "kpp", "ogrn", "legal_address", "actual_address",
                "bank_name", "bik", "correspondent_account",
                "settlement_account", "order_email", "phone", "comment",
                "is_active", "archived_at", "archived_by_user_id",
                "created_at", "updated_at",
            },
        )
        indexes = {
            index["name"]: index
            for index in inspector.get_indexes("supply_suppliers")
        }
        self.assertIn("ix_supply_suppliers_tenant_active_name", indexes)
        self.assertTrue(
            indexes["uq_supply_suppliers_tenant_active_inn"]["unique"]
        )
        checks = {
            check["name"]
            for check in inspector.get_check_constraints("supply_suppliers")
        }
        self.assertIn("ck_supply_suppliers_archive_state", checks)

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO supply_suppliers "
                    "(id, tenant_id, display_name, inn, created_at, updated_at) "
                    "VALUES (:id, 'eclair', 'Новопак', '6671000001', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": str(uuid4())},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO supply_suppliers "
                    "(id, tenant_id, display_name, inn, created_at, updated_at) "
                    "VALUES (:id, 'other', 'Новопак', '6671000001', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": str(uuid4())},
            )
        with self.assertRaises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO supply_suppliers "
                    "(id, tenant_id, display_name, inn, created_at, updated_at) "
                    "VALUES (:id, 'eclair', 'Дубликат', '6671000001', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": str(uuid4())},
            )
        with self.assertRaises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO supply_suppliers "
                    "(id, tenant_id, display_name, is_active, created_at, "
                    "updated_at) VALUES (:id, 'eclair', "
                    "'Неконсистентный архив', false, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                ),
                {"id": str(uuid4())},
            )

        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
        self.assertNotIn("supply_suppliers", sa.inspect(engine).get_table_names())
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
