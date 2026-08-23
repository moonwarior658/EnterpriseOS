import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/20260824_0034_add_internal_transfer_document_type.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "iiko_internal_transfer_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load internal transfer migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IikoInternalTransferMigrationTests(unittest.TestCase):
    def _engine(self):
        engine = sa.create_engine("sqlite://")
        metadata = sa.MetaData()
        sa.Table(
            "iiko_document_writes",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("document_type", sa.String(32), nullable=False),
            sa.CheckConstraint(
                "document_type IN ('OUTGOING_INVOICE')",
                name="iiko_document_type",
            ),
        )
        metadata.create_all(engine)
        return engine

    def test_revision_follows_0033(self) -> None:
        migration = load_migration()
        self.assertEqual(migration.revision, "20260824_0034")
        self.assertEqual(migration.down_revision, "20260812_0033")

    def test_upgrade_allows_internal_transfer(self) -> None:
        engine = self._engine()
        with engine.begin() as connection:
            migration = load_migration()
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            connection.execute(sa.text(
                "INSERT INTO iiko_document_writes (id, document_type) "
                "VALUES (1, 'INTERNAL_TRANSFER')"
            ))
            value = connection.scalar(sa.text(
                "SELECT document_type FROM iiko_document_writes WHERE id = 1"
            ))
        self.assertEqual(value, "INTERNAL_TRANSFER")
        engine.dispose()

    def test_downgrade_fails_closed_when_transfer_exists(self) -> None:
        engine = self._engine()
        with engine.begin() as connection:
            migration = load_migration()
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            connection.execute(sa.text(
                "INSERT INTO iiko_document_writes (id, document_type) "
                "VALUES (1, 'INTERNAL_TRANSFER')"
            ))
            with self.assertRaisesRegex(RuntimeError, "document writes exist"):
                migration.downgrade()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
