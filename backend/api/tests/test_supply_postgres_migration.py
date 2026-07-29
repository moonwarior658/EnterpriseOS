import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import (
    Integer,
    Numeric,
    create_engine,
    event,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_current_user
from app.api.routes.public_supply import token_rate_guard
from app.automation.supply_actions import (
    SupplyAutomationContext,
    ensure_request_cycle,
)
from app.automation.local_actions import LocalAutomationActionExecutor
from app.automation.outbox import SqlAlchemyOutboxStore
from app.automation.scheduler import process_due_schedule
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.supply import (
    Department,
    SupplyDepartmentDebt,
    SupplyProduct,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyUnit,
)
from app.models.user import User
from app.models.automation import (
    AutomationExecution,
    AutomationSchedule,
    ExecutionStatus,
    OutboxEvent,
    OutboxStatus,
)
from app.supply.normalization import normalize_product_text
from app.supply.public_service import list_public_schedule_summaries
from app.supply.service import plan_supply_request


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

    def _assert_matching_schema(self) -> None:
        inspector = inspect(self.engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_request_lines")
        }
        self.assertTrue(
            {
                "parsed_name",
                "parsed_quantity",
                "parsed_unit_id",
                "match_status",
                "match_method",
                "matched_at",
                "matched_by_user_id",
                "match_confidence",
                "match_notes",
            }
            <= columns.keys()
        )
        self.assertIsInstance(columns["parsed_quantity"]["type"], Numeric)
        self.assertIsInstance(columns["match_confidence"]["type"], Numeric)
        self.assertFalse(columns["match_status"]["nullable"])
        foreign_keys = {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                tuple(key["referred_columns"]),
                key["options"].get("ondelete"),
            )
            for key in inspector.get_foreign_keys("supply_request_lines")
        }
        self.assertIn(
            (("parsed_unit_id",), "supply_units", ("id",), "RESTRICT"),
            foreign_keys,
        )
        self.assertIn(
            (("matched_by_user_id",), "users", ("id",), "RESTRICT"),
            foreign_keys,
        )
        checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "supply_request_lines"
            )
        }
        self.assertTrue(
            {
                "ck_supply_request_lines_match_status",
                "ck_supply_request_lines_match_method",
                "ck_supply_request_lines_parsed_quantity_positive",
                "ck_supply_request_lines_match_confidence",
            }
            <= checks
        )

    def _assert_product_card_schema_and_seed(self) -> None:
        inspector = inspect(self.engine)
        self.assertTrue(
            {
                "supply_product_categories",
                "supply_storage_zones",
            }
            <= set(inspector.get_table_names())
        )
        product_columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_products")
        }
        self.assertTrue(
            {
                "iiko_id",
                "category_id",
                "storage_zone_id",
                "archived_at",
                "archived_by_user_id",
            }
            <= product_columns.keys()
        )
        product_foreign_keys = {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                key["options"].get("ondelete"),
            )
            for key in inspector.get_foreign_keys("supply_products")
        }
        self.assertTrue(
            {
                (("category_id",), "supply_product_categories", "RESTRICT"),
                (("storage_zone_id",), "supply_storage_zones", "RESTRICT"),
                (("archived_by_user_id",), "users", "RESTRICT"),
            }
            <= product_foreign_keys
        )
        self.assertIn(
            "ck_supply_products_archive_state",
            {
                constraint["name"]
                for constraint in inspector.get_check_constraints(
                    "supply_products"
                )
            },
        )
        iiko_index = next(
            index
            for index in inspector.get_indexes("supply_products")
            if index["name"] == "uq_supply_products_tenant_iiko_id"
        )
        self.assertTrue(iiko_index["unique"])
        self.assertEqual(
            iiko_index["column_names"],
            ["tenant_id", "iiko_id"],
        )
        with self.engine.connect() as connection:
            zones = connection.execute(
                text(
                    "SELECT code, name FROM supply_storage_zones "
                    "WHERE tenant_id = 'eclair' ORDER BY sort_order"
                )
            ).all()
            category_count = connection.scalar(
                text("SELECT count(*) FROM supply_product_categories")
            )
        self.assertEqual(
            zones,
            [
                ("FREEZER", "Морозильник"),
                ("REFRIGERATOR", "Холодильник"),
                ("DRY_STORAGE", "Сухой склад"),
                ("PACKAGING_STORAGE", "Склад упаковки"),
                ("HOUSEHOLD_STORAGE", "Хозсклад"),
                ("FIXED_ASSETS", "Основные средства"),
                ("OTHER", "Другое"),
            ],
        )
        self.assertEqual(category_count, 0)

    def _assert_cycles_and_duplicates_schema(self) -> None:
        inspector = inspect(self.engine)
        self.assertIn(
            "supply_request_cycles",
            inspector.get_table_names(),
        )
        request_columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_requests")
        }
        line_columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_request_lines")
        }
        self.assertTrue(request_columns["cycle_id"]["nullable"])
        self.assertTrue(line_columns["duplicate_group_id"]["nullable"])
        self.assertFalse(line_columns["duplicate_status"]["nullable"])
        self.assertIn(
            "uq_supply_requests_tenant_department_direction_cycle",
            {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "supply_requests"
                )
            },
        )
        self.assertIn(
            "uq_supply_request_cycles_tenant_direction_date",
            {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "supply_request_cycles"
                )
            },
        )
        self.assertIn(
            (("cycle_id",), "supply_request_cycles", "RESTRICT"),
            {
                (
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    key["options"].get("ondelete"),
                )
                for key in inspector.get_foreign_keys("supply_requests")
            },
        )

    def _assert_public_supply_schema(self) -> None:
        inspector = inspect(self.engine)
        request_columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_requests")
        }
        self.assertTrue(
            {
                "public_token_hash",
                "public_token_expires_at",
                "public_author_name",
                "public_author_phone",
                "source_ip_hash",
                "public_created_at",
            }
            <= request_columns.keys()
        )
        self.assertTrue(
            all(
                request_columns[name]["nullable"]
                for name in (
                    "public_token_hash",
                    "public_token_expires_at",
                    "public_author_name",
                    "public_author_phone",
                    "source_ip_hash",
                    "public_created_at",
                )
            )
        )
        indexes = {
            index["name"]: index
            for index in inspector.get_indexes("supply_requests")
        }
        self.assertTrue(indexes["uq_supply_requests_public_token_hash"]["unique"])
        self.assertEqual(
            indexes["uq_supply_requests_public_token_hash"]["column_names"],
            ["public_token_hash"],
        )
        self.assertEqual(
            indexes["ix_supply_requests_source_ip_created"]["column_names"],
            ["source_ip_hash", "public_created_at"],
        )

    def _assert_planning_schema(self) -> None:
        inspector = inspect(self.engine)
        self.assertIn("supply_line_allocations", inspector.get_table_names())
        request_columns = {
            column["name"]
            for column in inspector.get_columns("supply_requests")
        }
        self.assertTrue({
            "planned_at", "planned_by_user_id", "cancelled_at",
            "cancelled_by_user_id", "cancellation_reason",
        } <= request_columns)
        alias_columns = {
            column["name"]
            for column in inspector.get_columns("supply_product_aliases")
        }
        self.assertTrue({
            "status", "successful_application_count",
            "last_applied_at", "created_by_user_id",
        } <= alias_columns)
        allocation_columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_line_allocations")
        }
        self.assertIsInstance(
            allocation_columns["planned_quantity"]["type"], Numeric
        )
        self.assertIn(
            "uq_supply_line_allocations_line_action",
            {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "supply_line_allocations"
                )
            },
        )

    def _assert_fulfillment_debt_schema(self) -> None:
        inspector = inspect(self.engine)
        self.assertTrue({
            "supply_department_debts",
            "supply_department_debt_events",
            "supply_request_line_debt_links",
        } <= set(inspector.get_table_names()))
        allocation_columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_line_allocations")
        }
        self.assertTrue({
            "fulfilled_quantity", "fulfilled_at",
            "fulfilled_by_user_id", "fulfillment_comment",
        } <= allocation_columns.keys())
        self.assertIsInstance(
            allocation_columns["fulfilled_quantity"]["type"], Numeric
        )
        request_columns = {
            column["name"]
            for column in inspector.get_columns("supply_requests")
        }
        self.assertTrue({
            "fulfilled_at", "fulfilled_by_user_id",
        } <= request_columns)
        debt_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("supply_department_debts")
        }
        self.assertTrue(debt_indexes["uq_supply_department_debts_active"]["unique"])
        self.assertEqual(
            debt_indexes["uq_supply_department_debts_active"]["column_names"],
            ["tenant_id", "department_id", "product_id", "unit_id"],
        )

    def _assert_unmatched_operations_schema(self) -> None:
        columns = {
            column["name"]: column
            for column in inspect(self.engine).get_columns(
                "supply_department_debts"
            )
        }
        self.assertIn("working_name", columns)
        self.assertFalse(columns["working_name"]["nullable"])
        self.assertTrue(columns["product_id"]["nullable"])

    def _assert_send_quantity_schema(self) -> None:
        columns = {
            column["name"]: column
            for column in inspect(self.engine).get_columns(
                "supply_request_lines"
            )
        }
        self.assertIn("send_quantity", columns)
        self.assertIn("working_name_override", columns)
        self.assertIsInstance(columns["send_quantity"]["type"], Numeric)
        self.assertTrue(columns["send_quantity"]["nullable"])
        self.assertTrue(columns["working_name_override"]["nullable"])
        self.assertIn(
            "ck_supply_request_lines_send_quantity_nonnegative",
            {
                constraint["name"]
                for constraint in inspect(self.engine).get_check_constraints(
                    "supply_request_lines"
                )
            },
        )

    def _assert_iiko_staging_schema(self) -> None:
        inspector = inspect(self.engine)
        self.assertTrue(
            {"iiko_sync_runs", "iiko_raw_entities"}
            <= set(inspector.get_table_names())
        )
        raw_columns = {
            column["name"]
            for column in inspector.get_columns("iiko_raw_entities")
        }
        self.assertTrue(
            {
                "tenant_id",
                "sync_run_id",
                "entity_type",
                "external_id",
                "payload",
                "payload_hash",
                "source_updated_at",
                "is_active",
            }
            <= raw_columns
        )
        unique_constraints = {
            constraint["name"]: constraint
            for constraint in inspector.get_unique_constraints(
                "iiko_raw_entities"
            )
        }
        self.assertEqual(
            unique_constraints[
                "uq_iiko_raw_entity_version"
            ]["column_names"],
            [
                "tenant_id",
                "entity_type",
                "external_id",
                "payload_hash",
            ],
        )

    def test_01_upgrade_downgrade_and_repeat_upgrade(self) -> None:
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
        catalog_line_signature = self._table_signature(
            "supply_request_lines"
        )

        command.upgrade(self.alembic_config, "20260727_0009")
        self.assertEqual(self._current_revision(), "20260727_0009")
        self._assert_matching_schema()
        with self.engine.connect() as connection:
            legacy_matching = connection.execute(
                text(
                    "SELECT raw_text, parsed_name, parsed_quantity, "
                    "parsed_unit_id, match_status, match_method, "
                    "matched_at, matched_by_user_id, match_confidence, "
                    "match_notes FROM supply_request_lines "
                    "WHERE id = '20000000-0000-0000-0000-000000000001'"
                )
            ).one()
        self.assertEqual(
            legacy_matching,
            (
                "Свободная строка",
                None,
                None,
                None,
                "UNPROCESSED",
                None,
                None,
                None,
                None,
                None,
            ),
        )

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO supply_products
                        (id, tenant_id, name, normalized_name,
                         default_unit_id, is_active)
                    VALUES
                        ('30000000-0000-0000-0000-000000000001', 'eclair',
                         'Миграционный товар', 'миграционный товар',
                         'b20cf0ae-cb8e-4b06-a3ea-a38057a02a01', true)
                    """
                )
            )

        command.upgrade(self.alembic_config, "20260727_0010")
        self.assertEqual(self._current_revision(), "20260727_0010")
        self._assert_product_card_schema_and_seed()
        with self.engine.connect() as connection:
            migrated_product = connection.execute(
                text(
                    "SELECT is_active, archived_at, archived_by_user_id "
                    "FROM supply_products WHERE id = "
                    "'30000000-0000-0000-0000-000000000001'"
                )
            ).one()
        self.assertEqual(migrated_product, (True, None, None))

        command.upgrade(self.alembic_config, "20260727_0011")
        self.assertEqual(self._current_revision(), "20260727_0011")
        self._assert_cycles_and_duplicates_schema()
        with self.engine.connect() as connection:
            legacy_request = connection.execute(
                text(
                    "SELECT cycle_id FROM supply_requests WHERE id = "
                    "'10000000-0000-0000-0000-000000000001'"
                )
            ).one()
            legacy_line = connection.execute(
                text(
                    "SELECT duplicate_group_id, duplicate_status "
                    "FROM supply_request_lines WHERE id = "
                    "'20000000-0000-0000-0000-000000000001'"
                )
            ).one()
        self.assertEqual(legacy_request, (None,))
        self.assertEqual(legacy_line, (None, "NONE"))

        command.upgrade(self.alembic_config, "20260727_0012")
        self.assertEqual(self._current_revision(), "20260727_0012")
        self._assert_public_supply_schema()
        with self.engine.connect() as connection:
            public_metadata = connection.execute(
                text(
                    "SELECT public_token_hash, public_token_expires_at, "
                    "public_author_name, public_author_phone, "
                    "source_ip_hash, public_created_at "
                    "FROM supply_requests WHERE id = "
                    "'10000000-0000-0000-0000-000000000001'"
                )
            ).one()
        self.assertEqual(public_metadata, (None, None, None, None, None, None))

        command.downgrade(self.alembic_config, "20260727_0011")
        self.assertEqual(self._current_revision(), "20260727_0011")
        self.assertNotIn(
            "public_token_hash",
            {
                column["name"]
                for column in inspect(self.engine).get_columns(
                    "supply_requests"
                )
            },
        )
        command.upgrade(self.alembic_config, "20260727_0012")
        self.assertEqual(self._current_revision(), "20260727_0012")
        self._assert_public_supply_schema()

        command.upgrade(self.alembic_config, "20260727_0013")
        self.assertEqual(self._current_revision(), "20260727_0013")
        self._assert_planning_schema()
        command.downgrade(self.alembic_config, "20260727_0012")
        self.assertEqual(self._current_revision(), "20260727_0012")
        self.assertNotIn(
            "supply_line_allocations", inspect(self.engine).get_table_names()
        )
        command.upgrade(self.alembic_config, "20260727_0013")
        self.assertEqual(self._current_revision(), "20260727_0013")
        self._assert_planning_schema()

        command.upgrade(self.alembic_config, "20260727_0014")
        self.assertEqual(self._current_revision(), "20260727_0014")
        self._assert_fulfillment_debt_schema()
        command.downgrade(self.alembic_config, "20260727_0013")
        self.assertEqual(self._current_revision(), "20260727_0013")
        self.assertNotIn(
            "supply_department_debts", inspect(self.engine).get_table_names()
        )
        command.upgrade(self.alembic_config, "20260727_0014")
        self.assertEqual(self._current_revision(), "20260727_0014")
        self._assert_fulfillment_debt_schema()

        command.upgrade(self.alembic_config, "20260727_0015")
        self.assertEqual(self._current_revision(), "20260727_0015")
        self._assert_unmatched_operations_schema()
        command.downgrade(self.alembic_config, "20260727_0014")
        self.assertEqual(self._current_revision(), "20260727_0014")
        debt_columns = {
            column["name"]: column
            for column in inspect(self.engine).get_columns(
                "supply_department_debts"
            )
        }
        self.assertNotIn("working_name", debt_columns)
        self.assertFalse(debt_columns["product_id"]["nullable"])
        command.upgrade(self.alembic_config, "20260727_0015")
        self.assertEqual(self._current_revision(), "20260727_0015")
        self._assert_unmatched_operations_schema()

        command.upgrade(self.alembic_config, "20260727_0016")
        self.assertEqual(self._current_revision(), "20260727_0016")
        command.upgrade(self.alembic_config, "20260728_0017")
        self.assertEqual(self._current_revision(), "20260728_0017")
        self._assert_send_quantity_schema()
        command.downgrade(self.alembic_config, "20260727_0016")
        self.assertEqual(self._current_revision(), "20260727_0016")
        self.assertNotIn(
            "send_quantity",
            {
                column["name"]
                for column in inspect(self.engine).get_columns(
                    "supply_request_lines"
                )
            },
        )
        self.assertNotIn(
            "working_name_override",
            {
                column["name"]
                for column in inspect(self.engine).get_columns(
                    "supply_request_lines"
                )
            },
        )
        command.upgrade(self.alembic_config, "20260728_0017")
        self.assertEqual(self._current_revision(), "20260728_0017")
        self._assert_send_quantity_schema()

        command.upgrade(self.alembic_config, "20260729_0018")
        self.assertEqual(self._current_revision(), "20260729_0018")
        self._assert_iiko_staging_schema()
        command.downgrade(self.alembic_config, "20260728_0017")
        self.assertEqual(self._current_revision(), "20260728_0017")
        self.assertNotIn(
            "iiko_sync_runs",
            inspect(self.engine).get_table_names(),
        )
        self.assertNotIn(
            "iiko_raw_entities",
            inspect(self.engine).get_table_names(),
        )
        command.upgrade(self.alembic_config, "20260729_0018")
        self.assertEqual(self._current_revision(), "20260729_0018")
        self._assert_iiko_staging_schema()

        command.downgrade(self.alembic_config, "20260727_0010")
        self.assertEqual(self._current_revision(), "20260727_0010")
        self.assertNotIn(
            "supply_request_cycles",
            inspect(self.engine).get_table_names(),
        )
        command.upgrade(self.alembic_config, "20260727_0011")
        self.assertEqual(self._current_revision(), "20260727_0011")
        self._assert_cycles_and_duplicates_schema()

        command.downgrade(self.alembic_config, "20260727_0009")
        self.assertEqual(self._current_revision(), "20260727_0009")
        self._assert_matching_schema()
        self.assertTrue(
            {
                "supply_product_categories",
                "supply_storage_zones",
            }.isdisjoint(inspect(self.engine).get_table_names())
        )

        command.upgrade(self.alembic_config, "20260727_0010")
        self.assertEqual(self._current_revision(), "20260727_0010")
        self._assert_product_card_schema_and_seed()

        command.downgrade(self.alembic_config, "20260727_0008")
        self.assertEqual(self._current_revision(), "20260727_0008")
        self.assertEqual(
            self._table_signature("supply_request_lines"),
            catalog_line_signature,
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

        command.upgrade(self.alembic_config, "20260727_0009")
        self.assertEqual(self._current_revision(), "20260727_0009")
        self._assert_matching_schema()

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

    def test_02_public_mutations_lock_only_supply_request_row(self) -> None:
        command.upgrade(self.alembic_config, "head")
        self.assertEqual(self._current_revision(), "20260729_0018")
        self._assert_send_quantity_schema()
        self._assert_iiko_staging_schema()

        previous_tenant_id = settings.default_tenant_id
        settings.default_tenant_id = "eclair"
        token_rate_guard.clear()
        session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        with session_factory.begin() as session:
            department = session.query(Department).filter_by(
                tenant_id="eclair", code="ATO"
            ).one()
            direction = session.query(SupplyRequestDirection).filter_by(
                tenant_id="eclair", code="MAIN"
            ).one()
            unit = session.query(SupplyUnit).filter_by(
                tenant_id="eclair", code="KG"
            ).one()
            cycle = SupplyRequestCycle(
                tenant_id="eclair",
                direction_id=direction.id,
                cycle_date=date.today() + timedelta(days=30),
                opens_at=now - timedelta(hours=1),
                closes_at=now + timedelta(hours=1),
                hard_closes_at=now + timedelta(hours=2),
                status="OPEN",
            )
            product_name = "PostgreSQL тестовый продукт"
            session.add_all([
                cycle,
                SupplyProduct(
                    tenant_id="eclair",
                    name=product_name,
                    normalized_name=normalize_product_text(product_name),
                    default_unit_id=unit.id,
                    request_direction_id=direction.id,
                ),
            ])
            session.flush()
            department_id = department.id
            cycle_id = cycle.id

        lock_statements: list[str] = []

        def capture_lock_statement(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            if "FOR UPDATE" in statement.upper():
                lock_statements.append(statement)

        def override_get_db():
            with session_factory() as session:
                yield session

        event.listen(
            self.engine, "before_cursor_execute", capture_lock_statement
        )
        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app, client=("127.0.0.1", 50000))
        try:
            created_response = client.post(
                "/public/supply/requests",
                json={
                    "department_id": str(department_id),
                    "cycle_id": str(cycle_id),
                    "author_name": "PostgreSQL test",
                    "author_phone": None,
                    "multiline_text": f"{product_name} 1 кг",
                },
            )
            self.assertEqual(
                created_response.status_code, 201, created_response.text
            )
            created = created_response.json()
            token = created["public_token"]

            first_edit_response = client.put(
                f"/public/supply/requests/{token}/lines",
                json={
                    "expected_version": created["version"],
                    "multiline_text": f"{product_name} 2 кг",
                },
            )
            self.assertEqual(
                first_edit_response.status_code, 200, first_edit_response.text
            )
            first_edit = first_edit_response.json()
            self.assertEqual(first_edit["version"], 2)

            recognize_response = client.post(
                f"/public/supply/requests/{token}/recognize",
                json={"expected_version": first_edit["version"]},
            )
            self.assertEqual(
                recognize_response.status_code, 200, recognize_response.text
            )
            recognized = recognize_response.json()

            second_edit_response = client.put(
                f"/public/supply/requests/{token}/lines",
                json={
                    "expected_version": recognized["version"],
                    "multiline_text": f"{product_name} 3 кг",
                },
            )
            self.assertEqual(
                second_edit_response.status_code,
                200,
                second_edit_response.text,
            )
            second_edit = second_edit_response.json()
            self.assertEqual(
                second_edit["version"], recognized["version"] + 1
            )

            stale_edit_response = client.put(
                f"/public/supply/requests/{token}/lines",
                json={
                    "expected_version": recognized["version"],
                    "multiline_text": f"{product_name} 4 кг",
                },
            )
            self.assertEqual(stale_edit_response.status_code, 409)
            self.assertEqual(
                stale_edit_response.json()["detail"]["code"],
                "SUPPLY_REQUEST_VERSION_CONFLICT",
            )
            self.assertEqual(
                stale_edit_response.json()["detail"]["current_version"],
                second_edit["version"],
            )

            submit_response = client.post(
                f"/public/supply/requests/{token}/submit",
                json={"expected_version": second_edit["version"]},
            )
            self.assertEqual(
                submit_response.status_code, 200, submit_response.text
            )
            self.assertEqual(submit_response.json()["status"], "SUBMITTED")
        finally:
            app.dependency_overrides.clear()
            token_rate_guard.clear()
            event.remove(
                self.engine,
                "before_cursor_execute",
                capture_lock_statement,
            )
            settings.default_tenant_id = previous_tenant_id

        self.assertGreaterEqual(len(lock_statements), 5)
        for statement in lock_statements:
            normalized = " ".join(statement.upper().split())
            self.assertNotIn(" JOIN ", normalized)
            self.assertIn("FOR UPDATE OF SUPPLY_REQUESTS", normalized)

    def test_03_parallel_cycle_ensure_uses_unique_race_guard(self) -> None:
        command.upgrade(self.alembic_config, "head")
        session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        requested_at = datetime(
            2027,
            3,
            15,
            10,
            0,
            tzinfo=timezone.utc,
        )
        barrier = Barrier(2)
        payload = {
            "direction_code": "MAIN",
            "cycle_date_offset_days": 0,
            "opens_time": "00:00",
            "closes_time": "23:59",
            "hard_closes_time": "00:10",
            "hard_close_next_day": True,
            "timezone": "Asia/Yekaterinburg",
            "initial_status": "OPEN",
        }

        def execute_once() -> dict[str, object]:
            with session_factory.begin() as session:
                return ensure_request_cycle(
                    session,
                    SupplyAutomationContext(
                        execution_id=uuid4(),
                        tenant_id="eclair",
                        requested_at=requested_at,
                        executed_at=requested_at,
                    ),
                    payload,
                    before_insert=barrier.wait,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: execute_once(), range(2)))

        self.assertEqual(
            {result["outcome"] for result in results},
            {"created", "already_exists"},
        )
        self.assertEqual(
            {result["cycle_id"] for result in results},
            {results[0]["cycle_id"]},
        )
        with session_factory() as session:
            direction = session.query(SupplyRequestDirection).filter_by(
                tenant_id="eclair",
                code="MAIN",
            ).one()
            count = session.scalar(
                select(func.count())
                .select_from(SupplyRequestCycle)
                .where(
                    SupplyRequestCycle.tenant_id == "eclair",
                    SupplyRequestCycle.direction_id == direction.id,
                    SupplyRequestCycle.cycle_date
                    == date(2027, 3, 15),
                )
            )
        self.assertEqual(count, 1)

    def test_04_scheduler_outbox_local_handler_persists_result(self) -> None:
        command.upgrade(self.alembic_config, "head")
        session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        due_at = datetime(
            2027,
            4,
            6,
            19,
            0,
            tzinfo=timezone.utc,
        )
        with session_factory.begin() as session:
            schedule = AutomationSchedule(
                name="PostgreSQL Supply cycle action",
                automation_type="supply.ensure_request_cycle",
                tenant_id="eclair",
                scope_type="company",
                scope_id=None,
                schedule_config={
                    "type": "weekly",
                    "weekdays": [1, 4],
                    "time": "00:00",
                },
                payload={
                    "direction_code": "MAIN",
                    "cycle_date_offset_days": 0,
                    "opens_time": "00:00",
                    "closes_time": "23:59",
                    "hard_closes_time": "00:10",
                    "hard_close_next_day": True,
                    "timezone": "Asia/Yekaterinburg",
                    "initial_status": "OPEN",
                },
                recipients=[],
                timezone="Asia/Yekaterinburg",
                is_enabled=True,
                next_run_at=due_at,
                created_by_user_id=91001,
            )
            session.add(schedule)
            session.flush()
            schedule_id = schedule.id
            summaries = list_public_schedule_summaries(session)
            self.assertEqual(len(summaries), 1)
            self.assertIn("Основной", summaries[0])
            self.assertIn("приём до 23:59", summaries[0])
            self.assertNotIn("MAIN", summaries[0])

        with session_factory.begin() as session:
            schedule = session.get(AutomationSchedule, schedule_id)
            assert schedule is not None
            execution = process_due_schedule(
                session,
                schedule,
                now=due_at,
            )
            self.assertIsNotNone(execution)
            assert execution is not None
            execution_id = execution.execution_id

        store = SqlAlchemyOutboxStore(session_factory)
        claim = store.claim_next(
            worker_id="postgres-supply-test",
            claimed_at=due_at + timedelta(seconds=1),
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        LocalAutomationActionExecutor(session_factory).execute(
            claim,
            executed_at=due_at + timedelta(seconds=1),
        )

        with session_factory() as session:
            execution = session.scalar(
                select(AutomationExecution).where(
                    AutomationExecution.execution_id == execution_id
                )
            )
            event_row = session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.execution_id == execution_id
                )
            )
            self.assertIsNotNone(execution)
            self.assertIsNotNone(event_row)
            assert execution is not None and event_row is not None
            self.assertEqual(
                execution.status,
                ExecutionStatus.SUCCEEDED,
            )
            self.assertEqual(execution.provider, "enterpriseos")
            self.assertEqual(execution.result["outcome"], "created")
            self.assertEqual(
                execution.result["direction_code"],
                "MAIN",
            )
            self.assertEqual(event_row.status, OutboxStatus.PUBLISHED)

    def test_05_unmatched_simple_fulfillment_debt_full_flow(self) -> None:
        command.upgrade(self.alembic_config, "head")
        previous_tenant_id = settings.default_tenant_id
        settings.default_tenant_id = "eclair"
        session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        with session_factory.begin() as session:
            department = session.query(Department).filter_by(
                tenant_id="eclair", code="ATO"
            ).one()
            direction = session.query(SupplyRequestDirection).filter_by(
                tenant_id="eclair", code="MAIN"
            ).one()
            unit = session.query(SupplyUnit).filter_by(
                tenant_id="eclair", code="KG"
            ).one()
            cycle = SupplyRequestCycle(
                tenant_id="eclair",
                direction_id=direction.id,
                cycle_date=date.today() + timedelta(days=90),
                opens_at=now - timedelta(hours=1),
                closes_at=now + timedelta(hours=1),
                status="OPEN",
            )
            session.add(cycle)
            session.flush()
            supply_request = SupplyRequest(
                tenant_id="eclair",
                public_number=f"ЗАЯВКА-PG-{uuid4().hex[:10]}",
                department_id=department.id,
                direction_id=direction.id,
                cycle_id=cycle.id,
                status="SUBMITTED",
                source_type="INTERNAL",
                raw_input="Редкий ингредиент 3 кг",
                submitted_at=now,
                version=1,
            )
            session.add(supply_request)
            session.flush()
            line = SupplyRequestLine(
                request_id=supply_request.id,
                position=1,
                raw_text="Редкий ингредиент 3 кг",
                parsed_name="Редкий ингредиент",
                quantity=3,
                send_quantity=2,
                requested_unit_id=unit.id,
                product_id=None,
                match_status="NEEDS_REVIEW",
            )
            session.add(line)
            session.flush()
            request_id = supply_request.id
            line_id = line.id

        with session_factory() as session:
            result = plan_supply_request(
                session,
                request_id,
                expected_version=1,
                user_id=91001,
                simple_mode=True,
            )
            self.assertEqual(result.status, "PARTIALLY_FULFILLED")
            self.assertEqual(result.lines[0].unresolved_quantity, 1)
            self.assertIsNotNone(result.lines[0].active_debt_id)

        def override_get_db():
            with session_factory() as session:
                yield session

        def override_current_user():
            with session_factory() as session:
                return session.get(User, 91001)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        client = TestClient(app)
        try:
            detail = client.get(f"/supply/requests/{request_id}")
            debts = client.get(
                "/supply/debts",
                params={
                    "status": "ACTIVE",
                    "search": "Редкий ингредиент",
                },
            )
            dashboard = client.get("/supply/summary/dashboard")
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(debts.status_code, 200, debts.text)
            self.assertEqual(dashboard.status_code, 200, dashboard.text)
            detail_line = detail.json()["lines"][0]
            debt = debts.json()["items"][0]
            self.assertEqual(detail_line["id"], str(line_id))
            self.assertEqual(detail_line["unresolved_quantity"], "1.000")
            self.assertEqual(detail_line["active_debt_quantity"], "1.000")
            self.assertEqual(debts.json()["total"], 1)
            self.assertIsNone(debt["product"])
            self.assertEqual(debt["working_name"], "Редкий ингредиент")
            self.assertEqual(debt["outstanding_quantity"], "1.000")
            self.assertEqual(dashboard.json()["active_debts"], 1)
            with session_factory() as session:
                rows = session.scalars(
                    select(SupplyDepartmentDebt).where(
                        SupplyDepartmentDebt.first_request_line_id == line_id,
                    )
                ).all()
                self.assertEqual(len(rows), 1)
        finally:
            app.dependency_overrides.clear()
            settings.default_tenant_id = previous_tenant_id


if __name__ == "__main__":
    unittest.main()
