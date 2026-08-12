import importlib.util
import unittest
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260812_0032_split_iiko_document_identity.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_document_identity_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load iiko identity migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoDocumentIdentityMigrationTests(unittest.TestCase):
    def test_revision_follows_0031(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260812_0032")
        self.assertEqual(migration.down_revision, "20260811_0031")

    def test_upgrade_preserves_client_id_and_leaves_iiko_id_null(self) -> None:
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        table = sa.Table(
            "iiko_document_writes",
            metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("iiko_document_id", sa.Uuid(), nullable=False),
            sa.UniqueConstraint(
                "iiko_document_id",
                name="uq_iiko_document_writes_iiko_document_id",
            ),
        )
        metadata.create_all(engine)
        row_id = uuid4()
        old_id = uuid4()
        with engine.begin() as connection:
            connection.execute(table.insert().values(
                id=row_id,
                iiko_document_id=old_id,
            ))
            migration = load_migration()
            migration.op = Operations(
                MigrationContext.configure(connection)
            )
            migration.upgrade()
            migrated = connection.execute(sa.text(
                "SELECT client_document_id, iiko_document_id "
                "FROM iiko_document_writes WHERE id = :id"
            ), {"id": row_id.hex}).mappings().one()

        self.assertEqual(migrated["client_document_id"], old_id.hex)
        self.assertIsNone(migrated["iiko_document_id"])
        columns = {
            item["name"]: item
            for item in sa.inspect(engine).get_columns(
                "iiko_document_writes"
            )
        }
        self.assertFalse(columns["client_document_id"]["nullable"])
        self.assertTrue(columns["iiko_document_id"]["nullable"])
        unique_constraints = {
            item["name"]: tuple(item["column_names"])
            for item in sa.inspect(engine).get_unique_constraints(
                "iiko_document_writes"
            )
        }
        self.assertEqual(unique_constraints, {
            "uq_iiko_document_writes_client_document_id": (
                "client_document_id",
            ),
            "uq_iiko_document_writes_iiko_document_id": (
                "iiko_document_id",
            ),
        })
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
