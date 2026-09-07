import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.user import User


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "SUPPLY_TEST_DATABASE_URL is not configured for an isolated PostgreSQL",
)
class SupplySuppliersPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql"):
            raise RuntimeError("Migration test requires PostgreSQL")
        if url.host not in ALLOWED_HOSTS:
            raise RuntimeError("Migration test accepts only local PostgreSQL")
        if url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError(
                f"Migration test database must be {EXPECTED_DATABASE_NAME}"
            )

        cls.previous_database_settings = (
            settings.postgres_db,
            settings.postgres_user,
            settings.postgres_password,
            settings.postgres_host,
            settings.postgres_port,
        )
        settings.postgres_db = url.database
        settings.postgres_user = url.username or ""
        settings.postgres_password = url.password or ""
        settings.postgres_host = url.host or ""
        settings.postgres_port = url.port or 5432

        cls.engine = create_engine(TEST_DATABASE_URL)
        existing_tables = inspect(cls.engine).get_table_names()
        if existing_tables:
            cls.engine.dispose()
            cls._restore_settings()
            raise RuntimeError(
                "Migration test database must be empty; "
                f"found tables: {existing_tables}"
            )
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.alembic_config = Config(
            str(Path(__file__).parents[1] / "alembic.ini")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "previous_database_settings"):
            cls._restore_settings()

    @classmethod
    def _restore_settings(cls) -> None:
        (
            settings.postgres_db,
            settings.postgres_user,
            settings.postgres_password,
            settings.postgres_host,
            settings.postgres_port,
        ) = cls.previous_database_settings

    def _current_revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    @staticmethod
    def _payload(display_name: str, inn: str) -> dict:
        return {"display_name": display_name, "inn": inn}

    def test_migration_cycle_partial_index_and_api_conflicts(self) -> None:
        command.upgrade(self.alembic_config, "20260824_0034")
        self.assertEqual(self._current_revision(), "20260824_0034")

        command.upgrade(self.alembic_config, "20260907_0035")
        self.assertEqual(self._current_revision(), "20260907_0035")
        self.assertIn("supply_suppliers", inspect(self.engine).get_table_names())

        command.downgrade(self.alembic_config, "20260824_0034")
        self.assertEqual(self._current_revision(), "20260824_0034")
        self.assertNotIn(
            "supply_suppliers", inspect(self.engine).get_table_names()
        )

        command.upgrade(self.alembic_config, "20260907_0035")
        self.assertEqual(self._current_revision(), "20260907_0035")

        with self.engine.connect() as connection:
            index_definition = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND indexname = "
                    "'uq_supply_suppliers_tenant_active_inn'"
                )
            ).scalar_one()
        self.assertIn("UNIQUE INDEX", index_definition)
        self.assertIn("inn IS NOT NULL", index_definition)
        self.assertIn("is_active = true", index_definition)

        with self.sessions.begin() as session:
            session.add_all(
                [
                    User(
                        id=91001,
                        username="supplier-admin",
                        display_name="Supplier Admin",
                        hashed_password="unused",
                        tenant_id="eclair",
                        is_active=True,
                        is_admin=True,
                    ),
                    User(
                        id=91002,
                        username="supplier-other-admin",
                        display_name="Supplier Other Admin",
                        hashed_password="unused",
                        tenant_id="other",
                        is_active=True,
                        is_admin=True,
                    ),
                ]
            )

        current_user_id = 91001

        def override_get_db():
            with self.sessions() as session:
                yield session

        def override_current_user():
            with self.sessions() as session:
                return session.get(User, current_user_id)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        app.openapi_schema = None
        client = TestClient(app)

        first = client.post(
            "/supply/suppliers",
            json=self._payload("Первый", "6671000001"),
        )
        self.assertEqual(first.status_code, 201, first.text)

        with patch(
            "app.supply.service._active_supplier_inn_exists",
            return_value=False,
        ):
            duplicate_create = client.post(
                "/supply/suppliers",
                json=self._payload("Дубликат", "6671000001"),
            )
        self.assertEqual(duplicate_create.status_code, 409, duplicate_create.text)

        current_user_id = 91002
        other_tenant = client.post(
            "/supply/suppliers",
            json=self._payload("Другой tenant", "6671000001"),
        )
        self.assertEqual(other_tenant.status_code, 201, other_tenant.text)

        current_user_id = 91001
        archived = client.post(
            f"/supply/suppliers/{first.json()['id']}/archive"
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertFalse(archived.json()["is_active"])

        replacement = client.post(
            "/supply/suppliers",
            json=self._payload("Второй", "6671000001"),
        )
        self.assertEqual(replacement.status_code, 201, replacement.text)

        restore_conflict = client.post(
            f"/supply/suppliers/{first.json()['id']}/restore"
        )
        self.assertEqual(restore_conflict.status_code, 409, restore_conflict.text)

        with patch(
            "app.supply.service._active_supplier_inn_exists",
            return_value=False,
        ):
            database_restore_conflict = client.post(
                f"/supply/suppliers/{first.json()['id']}/restore"
            )
        self.assertEqual(
            database_restore_conflict.status_code,
            409,
            database_restore_conflict.text,
        )

        update_target = client.post(
            "/supply/suppliers",
            json=self._payload("Для обновления", "6671000002"),
        )
        self.assertEqual(update_target.status_code, 201, update_target.text)
        with patch(
            "app.supply.service._active_supplier_inn_exists",
            return_value=False,
        ):
            update_conflict = client.patch(
                f"/supply/suppliers/{update_target.json()['id']}",
                json={"inn": "6671000001"},
            )
        self.assertEqual(update_conflict.status_code, 409, update_conflict.text)

        with self.sessions() as session:
            archived_row = session.execute(
                text(
                    "SELECT is_active FROM supply_suppliers WHERE id = :id"
                ),
                {"id": first.json()["id"]},
            ).scalar_one()
            update_target_inn = session.execute(
                text("SELECT inn FROM supply_suppliers WHERE id = :id"),
                {"id": update_target.json()["id"]},
            ).scalar_one()
        self.assertFalse(archived_row)
        self.assertEqual(update_target_inn, "6671000002")


if __name__ == "__main__":
    unittest.main()
