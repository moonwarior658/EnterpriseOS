import os
import unittest
from pathlib import Path

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Integer, Numeric, create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "SUPPLY_TEST_DATABASE_URL is not configured for an isolated PostgreSQL",
)
class SupplyPostgresMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql"):
            raise RuntimeError("Migration test requires PostgreSQL")
        if url.host not in ALLOWED_HOSTS:
            raise RuntimeError(
                "Migration test accepts only a local isolated PostgreSQL"
            )
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

        try:
            cls.engine = create_engine(TEST_DATABASE_URL)
            existing_tables = inspect(cls.engine).get_table_names()
        except Exception:
            if hasattr(cls, "engine"):
                cls.engine.dispose()
            cls._restore_settings()
            raise
        if existing_tables:
            cls.engine.dispose()
            cls._restore_settings()
            raise RuntimeError(
                "Migration test database must be empty; "
                f"found tables: {existing_tables}"
            )

        cls.alembic_config = Config(
            str(Path(__file__).parents[1] / "alembic.ini")
        )

    @classmethod
    def tearDownClass(cls) -> None:
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

    def _table_signature(self, table_name: str) -> list[tuple]:
        return [
            (column["name"], str(column["type"]), column["nullable"])
            for column in inspect(self.engine).get_columns(table_name)
        ]

    def _assert_supply_schema_and_seed(self) -> None:
        inspector = inspect(self.engine)
        table_names = set(inspector.get_table_names())
        self.assertTrue(
            {
                "departments",
                "supply_request_directions",
                "supply_requests",
                "supply_request_lines",
            }
            <= table_names
        )

        columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_requests")
        }
        self.assertIsInstance(columns["created_by_user_id"]["type"], Integer)
        self.assertIsInstance(
            columns["source_work_request_id"]["type"],
            Integer,
        )
        foreign_keys = {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                tuple(key["referred_columns"]),
                key["options"].get("ondelete"),
            )
            for key in inspector.get_foreign_keys("supply_requests")
        }
        self.assertIn(
            (("created_by_user_id",), "users", ("id",), "RESTRICT"),
            foreign_keys,
        )
        self.assertIn(
            (
                ("source_work_request_id",),
                "work_requests",
                ("id",),
                "RESTRICT",
            ),
            foreign_keys,
        )
        self.assertIn(
            (("department_id",), "departments", ("id",), "RESTRICT"),
            foreign_keys,
        )
        self.assertIn(
            (
                ("direction_id",),
                "supply_request_directions",
                ("id",),
                "RESTRICT",
            ),
            foreign_keys,
        )
        line_foreign_keys = {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                tuple(key["referred_columns"]),
                key["options"].get("ondelete"),
            )
            for key in inspector.get_foreign_keys("supply_request_lines")
        }
        self.assertIn(
            (
                ("request_id",),
                "supply_requests",
                ("id",),
                "CASCADE",
            ),
            line_foreign_keys,
        )

        unique_constraints = {
            constraint["name"]
            for table_name in (
                "departments",
                "supply_request_directions",
                "supply_requests",
                "supply_request_lines",
            )
            for constraint in inspector.get_unique_constraints(table_name)
        }
        self.assertTrue(
            {
                "uq_departments_tenant_code",
                "uq_supply_request_directions_tenant_code",
                "uq_supply_requests_tenant_public_number",
                "uq_supply_request_lines_request_position",
            }
            <= unique_constraints
        )
        check_constraints = {
            constraint["name"]
            for table_name in ("supply_requests", "supply_request_lines")
            for constraint in inspector.get_check_constraints(table_name)
        }
        self.assertTrue(
            {
                "ck_supply_requests_status",
                "ck_supply_requests_source_type",
                "ck_supply_requests_version",
                "ck_supply_request_lines_position",
                "ck_supply_request_lines_raw_text",
            }
            <= check_constraints
        )

        with self.engine.connect() as connection:
            department_codes = connection.execute(
                text(
                    "SELECT code FROM departments "
                    "WHERE tenant_id = 'eclair' ORDER BY display_order"
                )
            ).scalars().all()
            direction_codes = connection.execute(
                text(
                    "SELECT code FROM supply_request_directions "
                    "WHERE tenant_id = 'eclair' ORDER BY display_order"
                )
            ).scalars().all()
        self.assertEqual(
            department_codes,
            ["М15", "М35", "М6А", "ЦЕХ", "ATO"],
        )
        self.assertEqual(direction_codes, ["MAIN", "HOUSEHOLD"])
        self.assertTrue(
            set(department_codes).isdisjoint(
                {"KITCHEN", "WORKSHOP_GH", "BAR_GH", "СКЛ"}
            )
        )

    def _assert_catalog_schema_and_seed(self) -> None:
        inspector = inspect(self.engine)
        table_names = set(inspector.get_table_names())
        self.assertTrue(
            {
                "supply_units",
                "supply_products",
                "supply_product_aliases",
            }
            <= table_names
        )
        line_columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_request_lines")
        }
        self.assertTrue(
            {"product_id", "requested_unit_id", "quantity"} <= line_columns.keys()
        )
        self.assertIsInstance(line_columns["quantity"]["type"], Numeric)
        self.assertTrue(line_columns["product_id"]["nullable"])
        self.assertTrue(line_columns["requested_unit_id"]["nullable"])
        self.assertTrue(line_columns["quantity"]["nullable"])

        line_foreign_keys = {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                tuple(key["referred_columns"]),
                key["options"].get("ondelete"),
            )
            for key in inspector.get_foreign_keys("supply_request_lines")
        }
        self.assertIn(
            (("product_id",), "supply_products", ("id",), "RESTRICT"),
            line_foreign_keys,
        )
        self.assertIn(
            (
                ("requested_unit_id",),
                "supply_units",
                ("id",),
                "RESTRICT",
            ),
            line_foreign_keys,
        )
        unique_constraints = {
            constraint["name"]
            for table_name in (
                "supply_units",
                "supply_products",
                "supply_product_aliases",
            )
            for constraint in inspector.get_unique_constraints(table_name)
        }
        self.assertTrue(
            {
                "uq_supply_units_tenant_code",
                "uq_supply_products_tenant_normalized_name",
                "uq_supply_product_aliases_tenant_normalized_alias",
            }
            <= unique_constraints
        )
        check_constraints = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "supply_request_lines"
            )
        }
        self.assertIn(
            "ck_supply_request_lines_quantity_positive",
            check_constraints,
        )
        with self.engine.connect() as connection:
            units = connection.execute(
                text(
                    "SELECT code, short_name_ru, allows_fraction "
                    "FROM supply_units WHERE tenant_id = 'eclair' "
                    "ORDER BY code"
                )
            ).all()
        self.assertEqual(
            units,
            [
                ("BOX", "кор", False),
                ("KG", "кг", True),
                ("L", "л", True),
                ("PACK", "уп", False),
                ("PCS", "шт", False),
            ],
        )

    def test_upgrade_downgrade_and_repeat_upgrade(self) -> None:
        command.upgrade(self.alembic_config, "20260726_0006")
        self.assertEqual(self._current_revision(), "20260726_0006")

        users_signature = self._table_signature("users")
        work_requests_signature = self._table_signature("work_requests")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users
                        (id, username, display_name, hashed_password,
                         is_active, is_admin)
                    VALUES
                        (91001, 'migration-user', 'Migration User',
                         'unused', true, true)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO work_requests
                        (id, request_type, department, description, status,
                         warehouse_category, created_by_user_id)
                    VALUES
                        (92001, 'warehouse', 'М15', 'Migration request',
                         'new', 'products', 91001)
                    """
                )
            )

        command.upgrade(self.alembic_config, "20260727_0007")
        self.assertEqual(self._current_revision(), "20260727_0007")
        self._assert_supply_schema_and_seed()

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO supply_requests
                        (id, tenant_id, public_number, department_id,
                         direction_id, status, source_type, raw_input,
                         version, created_by_user_id)
                    VALUES
                        ('10000000-0000-0000-0000-000000000001', 'eclair',
                         'ЗАЯВКА-20260727-М15-MAIN-001',
                         'a29ac646-322f-47ab-8d31-d3d41fe1a510',
                         '377f8383-f21d-474a-bdf9-4d08edac669b',
                         'DRAFT', 'INTERNAL', 'Свободная строка', 1, 91001)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO supply_request_lines
                        (id, request_id, position, raw_text)
                    VALUES
                        ('20000000-0000-0000-0000-000000000001',
                         '10000000-0000-0000-0000-000000000001',
                         1, 'Свободная строка')
                    """
                )
            )
        foundation_line_signature = self._table_signature(
            "supply_request_lines"
        )

        command.upgrade(self.alembic_config, "20260727_0008")
        self.assertEqual(self._current_revision(), "20260727_0008")
        self._assert_supply_schema_and_seed()
        self._assert_catalog_schema_and_seed()
        with self.engine.connect() as connection:
            legacy_line = connection.execute(
                text(
                    "SELECT raw_text, product_id, requested_unit_id, quantity "
                    "FROM supply_request_lines "
                    "WHERE id = '20000000-0000-0000-0000-000000000001'"
                )
            ).one()
        self.assertEqual(
            legacy_line,
            ("Свободная строка", None, None, None),
        )

        command.downgrade(self.alembic_config, "20260727_0007")
        self.assertEqual(self._current_revision(), "20260727_0007")
        table_names = set(inspect(self.engine).get_table_names())
        self.assertTrue(
            {
                "supply_units",
                "supply_products",
                "supply_product_aliases",
            }.isdisjoint(table_names)
        )
        self.assertEqual(
            self._table_signature("supply_request_lines"),
            foundation_line_signature,
        )
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(
                    text(
                        "SELECT raw_text FROM supply_request_lines "
                        "WHERE id = "
                        "'20000000-0000-0000-0000-000000000001'"
                    )
                ),
                "Свободная строка",
            )

        command.upgrade(self.alembic_config, "20260727_0008")
        self.assertEqual(self._current_revision(), "20260727_0008")
        self._assert_catalog_schema_and_seed()
        self.assertEqual(self._table_signature("users"), users_signature)
        self.assertEqual(
            self._table_signature("work_requests"),
            work_requests_signature,
        )
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(
                    text("SELECT username FROM users WHERE id = 91001")
                ),
                "migration-user",
            )
            self.assertEqual(
                connection.scalar(
                    text(
                        "SELECT description FROM work_requests "
                        "WHERE id = 92001"
                    )
                ),
                "Migration request",
            )

        command.downgrade(self.alembic_config, "20260726_0006")
        self.assertEqual(self._current_revision(), "20260726_0006")
        table_names = set(inspect(self.engine).get_table_names())
        self.assertTrue({"users", "work_requests"} <= table_names)
        self.assertTrue(
            {
                "departments",
                "supply_request_directions",
                "supply_requests",
                "supply_request_lines",
            }.isdisjoint(table_names)
        )
        self.assertEqual(self._table_signature("users"), users_signature)
        self.assertEqual(
            self._table_signature("work_requests"),
            work_requests_signature,
        )
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(
                    text("SELECT count(*) FROM users WHERE id = 91001")
                ),
                1,
            )
            self.assertEqual(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM work_requests WHERE id = 92001"
                    )
                ),
                1,
            )

        command.upgrade(self.alembic_config, "20260727_0007")
        self.assertEqual(self._current_revision(), "20260727_0007")
        self._assert_supply_schema_and_seed()


if __name__ == "__main__":
    unittest.main()
