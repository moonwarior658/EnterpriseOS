import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event, local
from unittest.mock import patch
from uuid import UUID, uuid4

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
from sqlalchemy.exc import IntegrityError
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
    LegalContour,
    SupplyDepartmentDebt,
    SupplyDepartmentProductMapping,
    SupplyProduct,
    SupplyProductSourceMapping,
    SupplyProductSourceMappingAuditEvent,
    SupplyProductSourceRole,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyUnit,
    SupplyStockCalculation,
    SupplyStockCalculationAuditAction,
    SupplyStockCalculationAuditEvent,
    SupplyStockCalculationLine,
    SupplyStockCalculationStatus,
)
from app.models.iiko import (
    IikoMappingStatus,
    IikoProductMapping,
    IikoRawEntity,
    IikoStockBalanceSnapshotLine,
    IikoStockBalanceSnapshotSource,
    IikoStockBalanceSnapshotSourceStatus,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
    IikoUnitMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
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
from app.supply.service import (
    SupplyContextMappingVersionConflictError,
    bootstrap_permanent_milk_context_mappings,
    delete_context_mapping,
    plan_supply_request,
    recognize_supply_request,
    replace_context_mapping,
)
from app.supply import source_mapping as source_mapping_service
from app.supply.source_mapping import (
    SupplyProductSourceConcurrentAssignmentError,
    SupplyProductSourceVersionConflictError,
    assign_product_source,
    bootstrap_product_source_mappings,
)
from app.supply.stock_calculation import (
    SupplyStockCalculationBlockedError,
    SupplyStockCalculationConfirmedError,
    SupplyStockCalculationVersionConflictError,
    SupplyStockTransferFractionInvalidError,
    adjust_transferable_quantity,
    calculate_stock,
    confirm_stock_calculation,
)


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
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)

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

    def _seed_product_source_rows(
        self,
        *,
        tenant_id: str,
        product_ids: list[UUID],
        source_count: int = 1,
    ) -> tuple[int, list[UUID]]:
        actor_id = 10_000 + (uuid4().int % 1_000_000_000)
        unit_id = uuid4()
        source_ids: list[UUID] = []
        with self.sessions.begin() as session:
            session.add(User(
                id=actor_id,
                username=f"source-{tenant_id}",
                display_name="PostgreSQL SOURCE test",
                hashed_password="unused",
                is_active=True,
                is_admin=True,
            ))
            session.add(SupplyUnit(
                id=unit_id,
                tenant_id=tenant_id,
                code="KG",
                name_ru="Килограмм",
                short_name_ru="кг",
                allows_fraction=True,
            ))
            for position, product_id in enumerate(product_ids, start=1):
                session.add(SupplyProduct(
                    id=product_id,
                    tenant_id=tenant_id,
                    name=f"Товар {position}",
                    normalized_name=f"товар {position}",
                    default_unit_id=unit_id,
                ))
                session.add(IikoProductMapping(
                    tenant_id=tenant_id,
                    iiko_product_id=uuid4(),
                    eos_product_id=product_id,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name=f"т Товар {position}",
                ))
            for position in range(1, source_count + 1):
                source = IikoWarehouseMapping(
                    tenant_id=tenant_id,
                    iiko_warehouse_id=uuid4(),
                    destination_type=IikoWarehouseDestinationType.SOURCE,
                    role=IikoWarehouseRole.MAIN,
                    legal_contour=LegalContour.IP,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name=f"SOURCE {position}",
                )
                session.add(source)
                session.flush()
                source_ids.append(source.id)
        return actor_id, source_ids

    def _postgres_session(self):
        connection = self.engine.connect()
        connection.execute(text("SET lock_timeout = '5s'"))
        connection.execute(text("SET statement_timeout = '15s'"))
        connection.commit()
        return connection, sessionmaker(
            bind=connection,
            expire_on_commit=False,
        )()

    def _seed_stock_calculation_case(
        self,
        *,
        tenant_id: str | None = None,
        quantities: tuple[Decimal, ...] = (Decimal("6"), Decimal("6")),
        available: Decimal = Decimal("10"),
        allows_fraction: bool = True,
        include_source_mapping: bool = True,
        sync_run_id: UUID | None = None,
        sync_started_at: datetime | None = None,
        sync_finished_at: datetime | None = None,
    ) -> dict[str, object]:
        tenant_id = tenant_id or f"stock-{uuid4().hex[:10]}"
        actor_id = 100_000_000 + uuid4().int % 1_000_000_000
        now = datetime.now(timezone.utc)
        started_at = sync_started_at or now
        finished_at = sync_finished_at or now
        with self.sessions.begin() as session:
            actor = User(
                id=actor_id,
                username=f"stock-{uuid4().hex[:12]}",
                display_name="Stock PostgreSQL test",
                hashed_password="unused",
                is_active=True,
                is_admin=True,
            )
            unit = SupplyUnit(
                tenant_id=tenant_id,
                code="KG",
                name_ru="Килограмм",
                short_name_ru="кг",
                allows_fraction=allows_fraction,
            )
            department = Department(
                tenant_id=tenant_id,
                code="M15",
                name="M15",
                legal_contour=LegalContour.IP,
            )
            direction = SupplyRequestDirection(
                tenant_id=tenant_id,
                code="MAIN",
                name="Продукты",
            )
            product = SupplyProduct(
                tenant_id=tenant_id,
                name="Тестовый товар",
                normalized_name="тестовый товар",
                default_unit=unit,
            )
            session.add_all([actor, unit, department, direction, product])
            session.flush()
            source = IikoWarehouseMapping(
                tenant_id=tenant_id,
                iiko_warehouse_id=uuid4(),
                destination_type=IikoWarehouseDestinationType.SOURCE,
                role=IikoWarehouseRole.MAIN,
                legal_contour=LegalContour.IP,
                status=IikoMappingStatus.CONFIRMED,
                source_name="SOURCE PG",
            )
            request = SupplyRequest(
                tenant_id=tenant_id,
                public_number=f"STOCK-{uuid4().hex[:12]}",
                department=department,
                direction=direction,
                status="IN_REVIEW",
                source_type="INTERNAL",
                raw_input="Тестовый товар",
                created_by_user_id=actor_id,
            )
            session.add_all([source, request])
            session.flush()
            lines: list[SupplyRequestLine] = []
            for position, quantity in enumerate(quantities, start=1):
                line = SupplyRequestLine(
                    tenant_id=tenant_id,
                    request=request,
                    position=position,
                    raw_text=f"Тестовый товар {quantity}",
                    parsed_name="Тестовый товар",
                    product=product,
                    requested_unit=unit,
                    quantity=quantity,
                    match_status="MATCHED",
                    match_method="MANUAL",
                )
                session.add(line)
                lines.append(line)
            session.flush()
            iiko_product_id = uuid4()
            iiko_unit_id = uuid4()
            session.add_all([
                IikoProductMapping(
                    tenant_id=tenant_id,
                    iiko_product_id=iiko_product_id,
                    eos_product_id=product.id,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="т Тестовый товар",
                    source_unit_id=iiko_unit_id,
                ),
                IikoUnitMapping(
                    tenant_id=tenant_id,
                    iiko_unit_id=iiko_unit_id,
                    eos_unit_id=unit.id,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="кг",
                ),
            ])
            if include_source_mapping:
                session.add(SupplyProductSourceMapping(
                    tenant_id=tenant_id,
                    eos_product_id=product.id,
                    legal_contour=LegalContour.IP,
                    role=SupplyProductSourceRole.MAIN,
                    source_warehouse_mapping_id=source.id,
                    assigned_by_user_id=actor_id,
                ))
            run = IikoSyncRun(
                id=sync_run_id or uuid4(),
                tenant_id=tenant_id,
                sync_type=IikoSyncType.STOCK_BALANCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
                started_at=started_at,
                finished_at=finished_at,
                parameters={
                    "snapshot_at": finished_at.isoformat(),
                    "completed_source_warehouse_mapping_ids": [str(source.id)],
                },
            )
            session.add(run)
            session.flush()
            session.add(IikoStockBalanceSnapshotSource(
                tenant_id=tenant_id,
                sync_run_id=run.id,
                department_id=department.id,
                source_warehouse_mapping_id=source.id,
                snapshot_at=finished_at,
                status=IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
            ))
            session.flush()
            session.add(IikoStockBalanceSnapshotLine(
                tenant_id=tenant_id,
                sync_run_id=run.id,
                department_id=department.id,
                source_warehouse_mapping_id=source.id,
                iiko_warehouse_id=source.iiko_warehouse_id,
                iiko_product_id=iiko_product_id,
                iiko_unit_id=iiko_unit_id,
                quantity=available,
                snapshot_at=finished_at,
            ))
            return {
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "unit_id": unit.id,
                "department_id": department.id,
                "iiko_unit_id": iiko_unit_id,
                "product_id": product.id,
                "source_id": source.id,
                "warehouse_id": source.iiko_warehouse_id,
                "iiko_product_id": iiko_product_id,
                "request_id": request.id,
                "line_ids": [line.id for line in lines],
                "available": available,
            }

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

    def _assert_iiko_mapping_schema(self) -> None:
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        self.assertTrue(
            {
                "iiko_product_mappings",
                "iiko_unit_mappings",
                "iiko_warehouse_mappings",
                "iiko_mapping_audit_events",
            }
            <= tables
        )
        product_columns = {
            column["name"]
            for column in inspector.get_columns("iiko_product_mappings")
        }
        self.assertTrue(
            {
                "tenant_id",
                "iiko_product_id",
                "eos_product_id",
                "status",
                "is_deleted",
                "confidence",
                "reasons",
                "decided_by_user_id",
            }
            <= product_columns
        )
        warehouse_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("iiko_warehouse_mappings")
        }
        self.assertIn(
            "uq_iiko_warehouse_mappings_confirmed_role",
            warehouse_indexes,
        )

    def _assert_iiko_warehouse_destination_schema(self) -> None:
        inspector = inspect(self.engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("iiko_warehouse_mappings")
        }
        self.assertFalse(columns["destination_type"]["nullable"])
        self.assertTrue(
            {"source_direction", "source_priority"} <= columns.keys()
        )
        warehouse_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("iiko_warehouse_mappings")
        }
        self.assertIn(
            "uq_iiko_warehouse_mappings_confirmed_source_priority",
            warehouse_indexes,
        )

    def _assert_iiko_warehouse_legal_contour_schema(self) -> None:
        inspector = inspect(self.engine)
        warehouse_columns = {
            column["name"]
            for column in inspector.get_columns("iiko_warehouse_mappings")
        }
        self.assertIn("legal_contour", warehouse_columns)
        self.assertNotIn("source_priority", warehouse_columns)
        self.assertNotIn("source_direction", warehouse_columns)
        department_columns = {
            column["name"]
            for column in inspector.get_columns("departments")
        }
        self.assertIn("legal_contour", department_columns)

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

        command.upgrade(self.alembic_config, "20260729_0019")
        self.assertEqual(self._current_revision(), "20260729_0019")
        self._assert_iiko_mapping_schema()
        command.downgrade(self.alembic_config, "20260729_0018")
        self.assertEqual(self._current_revision(), "20260729_0018")
        self.assertNotIn(
            "iiko_product_mappings",
            inspect(self.engine).get_table_names(),
        )
        command.upgrade(self.alembic_config, "20260729_0019")
        self.assertEqual(self._current_revision(), "20260729_0019")
        self._assert_iiko_mapping_schema()
        legacy_mapping_id = "40000000-0000-0000-0000-000000000001"
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO iiko_warehouse_mappings
                        (id, tenant_id, iiko_warehouse_id, eos_department_id,
                         role, source_name, status, is_deleted, reasons)
                    VALUES
                        (:mapping_id, 'eclair',
                         '50000000-0000-0000-0000-000000000001',
                         'a29ac646-322f-47ab-8d31-d3d41fe1a510',
                         'MAIN', 'Старый склад подразделения',
                         'CONFIRMED', false, '[]'::jsonb)
                    """
                ),
                {"mapping_id": legacy_mapping_id},
            )
        command.upgrade(self.alembic_config, "20260730_0020")
        self.assertEqual(self._current_revision(), "20260730_0020")
        self._assert_iiko_warehouse_destination_schema()
        command.upgrade(self.alembic_config, "20260730_0021")
        self.assertEqual(self._current_revision(), "20260730_0021")
        self._assert_iiko_warehouse_legal_contour_schema()
        with self.engine.connect() as connection:
            legacy_mapping = connection.execute(
                text(
                    "SELECT destination_type, eos_department_id, role "
                    "FROM iiko_warehouse_mappings WHERE id = :mapping_id"
                ),
                {"mapping_id": legacy_mapping_id},
            ).one()
        self.assertEqual(legacy_mapping.destination_type, "DESTINATION")
        self.assertEqual(
            str(legacy_mapping.eos_department_id),
            "a29ac646-322f-47ab-8d31-d3d41fe1a510",
        )
        self.assertEqual(legacy_mapping.role, "MAIN")
        command.downgrade(self.alembic_config, "20260729_0019")
        self.assertEqual(self._current_revision(), "20260729_0019")
        self.assertNotIn(
            "destination_type",
            {
                column["name"]
                for column in inspect(self.engine).get_columns(
                    "iiko_warehouse_mappings"
                )
            },
        )
        command.upgrade(self.alembic_config, "20260730_0021")
        self.assertEqual(self._current_revision(), "20260730_0021")
        self._assert_iiko_warehouse_legal_contour_schema()
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

    def test_01b_product_source_migration_cycle(self) -> None:
        current_revision = self._current_revision()
        if current_revision == "20260803_0025":
            command.downgrade(self.alembic_config, "20260803_0024")
        else:
            command.upgrade(self.alembic_config, "20260803_0024")
        self.assertEqual(self._current_revision(), "20260803_0024")
        self.assertNotIn(
            "supply_product_source_mappings",
            inspect(self.engine).get_table_names(),
        )

        def assert_revision_0025() -> None:
            command.upgrade(self.alembic_config, "20260803_0025")
            self.assertEqual(self._current_revision(), "20260803_0025")
            inspector = inspect(self.engine)
            columns = {
                column["name"]: column
                for column in inspector.get_columns(
                    "supply_product_source_mappings"
                )
            }
            self.assertFalse(columns["version"]["nullable"])
            self.assertIn("1", str(columns["version"]["default"]))
            unique_constraints = {
                constraint["name"]: constraint["column_names"]
                for constraint in inspector.get_unique_constraints(
                    "supply_product_source_mappings"
                )
            }
            self.assertEqual(
                unique_constraints[
                    "uq_supply_product_source_mapping_product_contour"
                ],
                ["tenant_id", "eos_product_id", "legal_contour"],
            )
            check_constraints = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(
                    "supply_product_source_mappings"
                )
            }
            self.assertTrue({
                "ck_supply_product_source_mapping_version",
                "supply_product_source_legal_contour",
                "supply_product_source_role",
            } <= check_constraints)
            foreign_keys = {
                (
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    tuple(key["referred_columns"]),
                )
                for key in inspector.get_foreign_keys(
                    "supply_product_source_mappings"
                )
            }
            self.assertIn(
                (("eos_product_id",), "supply_products", ("id",)),
                foreign_keys,
            )
            self.assertIn(
                (
                    ("source_warehouse_mapping_id",),
                    "iiko_warehouse_mappings",
                    ("id",),
                ),
                foreign_keys,
            )
            self.assertIn(
                (("assigned_by_user_id",), "users", ("id",)),
                foreign_keys,
            )
            audit_foreign_keys = {
                (
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    tuple(key["referred_columns"]),
                )
                for key in inspector.get_foreign_keys(
                    "supply_product_source_mapping_audit_events"
                )
            }
            self.assertTrue({
                (("mapping_id",), "supply_product_source_mappings", ("id",)),
                (("actor_user_id",), "users", ("id",)),
            } <= audit_foreign_keys)

        assert_revision_0025()
        command.downgrade(self.alembic_config, "20260803_0024")
        self.assertEqual(self._current_revision(), "20260803_0024")
        self.assertNotIn(
            "supply_product_source_mappings",
            inspect(self.engine).get_table_names(),
        )
        assert_revision_0025()

    def test_01c_contextual_mapping_migration_cycle(self) -> None:
        command.upgrade(self.alembic_config, "20260804_0026")
        if self._current_revision() == "20260804_0026":
            command.downgrade(self.alembic_config, "20260803_0025")
        self.assertEqual(self._current_revision(), "20260803_0025")

        actor_id = 93011
        request_id = uuid4()
        line_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO users
                    (id, username, display_name, hashed_password,
                     is_active, is_admin)
                VALUES
                    (:actor_id, 'context-cycle-admin', 'Context cycle admin',
                     'unused', true, true)
                ON CONFLICT (id) DO NOTHING
            """), {"actor_id": actor_id})
            connection.execute(text("""
                INSERT INTO supply_requests
                    (id, tenant_id, public_number, department_id,
                     direction_id, status, source_type, raw_input,
                     version, created_by_user_id)
                SELECT
                    :request_id, 'eclair', :public_number, department.id,
                    direction.id, 'DRAFT', 'INTERNAL', 'молоко 1 л',
                    1, :actor_id
                FROM departments AS department
                CROSS JOIN supply_request_directions AS direction
                WHERE department.tenant_id = 'eclair'
                  AND department.code = 'М15'
                  AND direction.tenant_id = 'eclair'
                  AND direction.code = 'MAIN'
            """), {
                "request_id": request_id,
                "public_number": f"CTX-CYCLE-{request_id}",
                "actor_id": actor_id,
            })
            connection.execute(text("""
                INSERT INTO supply_request_lines
                    (id, request_id, position, raw_text)
                VALUES (:line_id, :request_id, 1, 'молоко 1 л')
            """), {"line_id": line_id, "request_id": request_id})

        command.upgrade(self.alembic_config, "20260804_0026")
        self.assertEqual(self._current_revision(), "20260804_0026")
        inspector = inspect(self.engine)
        mapping_columns = {
            column["name"]: column
            for column in inspector.get_columns(
                "supply_department_product_mappings"
            )
        }
        self.assertFalse(mapping_columns["version"]["nullable"])
        self.assertIn("1", str(mapping_columns["version"]["default"]))
        self.assertIn(
            "ck_supply_context_mapping_version",
            {
                item["name"]
                for item in inspector.get_check_constraints(
                    "supply_department_product_mappings"
                )
            },
        )
        mapping_foreign_keys = {
            (
                key["name"],
                tuple(key["constrained_columns"]),
                key["referred_table"],
                tuple(key["referred_columns"]),
            )
            for key in inspector.get_foreign_keys(
                "supply_department_product_mappings"
            )
        }
        self.assertIn(
            (
                "fk_supply_context_mapping_tenant_department",
                ("tenant_id", "department_id"),
                "departments",
                ("tenant_id", "id"),
            ),
            mapping_foreign_keys,
        )
        self.assertIn(
            (
                "fk_supply_context_mapping_tenant_product",
                ("tenant_id", "product_id"),
                "supply_products",
                ("tenant_id", "id"),
            ),
            mapping_foreign_keys,
        )
        with self.engine.begin() as connection:
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_department_product_mappings"
            )), 0)
            result = connection.execute(text("""
                UPDATE supply_request_lines
                SET match_method = 'CONTEXT_MAPPING'
                WHERE id = :line_id
            """), {"line_id": line_id})
            self.assertEqual(result.rowcount, 1)

        command.downgrade(self.alembic_config, "20260803_0025")
        self.assertEqual(self._current_revision(), "20260803_0025")
        self.assertNotIn(
            "supply_department_product_mappings",
            inspect(self.engine).get_table_names(),
        )
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("""
                SELECT match_method
                FROM supply_request_lines
                WHERE id = :line_id
            """), {"line_id": line_id}), "MANUAL")

        command.upgrade(self.alembic_config, "20260804_0026")
        self.assertEqual(self._current_revision(), "20260804_0026")
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_department_product_mappings"
            )), 0)

    def test_01d_contextual_mapping_postgres_contracts(self) -> None:
        command.upgrade(self.alembic_config, "20260804_0027")
        self.assertEqual(self._current_revision(), "20260804_0027")
        previous_tenant_id = settings.default_tenant_id
        tenant_suffix = uuid4().hex[:8]
        primary_tenant = f"context-primary-{tenant_suffix}"
        settings.default_tenant_id = primary_tenant
        actor_id = 93001
        now = datetime.now(timezone.utc)
        old_request_id = uuid4()
        old_line_id = uuid4()
        new_request_id = uuid4()
        new_line_id = uuid4()
        second_product_id = uuid4()
        conflict_tenant = f"context-conflict-{tenant_suffix}"
        other_tenant = f"context-other-{tenant_suffix}"
        try:
            with self.sessions.begin() as session:
                if session.get(User, actor_id) is None:
                    session.add(User(
                        id=actor_id,
                        username="context-admin",
                        display_name="Context admin",
                        hashed_password="unused",
                        is_active=True,
                        is_admin=True,
                    ))
                unit = SupplyUnit(
                    tenant_id=primary_tenant,
                    code="L",
                    name_ru="Литр",
                    short_name_ru="л",
                    allows_fraction=True,
                )
                direction = SupplyRequestDirection(
                    tenant_id=primary_tenant,
                    code="MAIN",
                    name="Основная заявка",
                )
                departments = [
                    Department(
                        tenant_id=primary_tenant,
                        code=code,
                        name=f"{primary_tenant} {code}",
                    )
                    for code in ("М15", "М35", "М6А", "ATO")
                ]
                session.add_all([unit, direction, *departments])
                session.flush()
                department = next(
                    item for item in departments if item.code == "М15"
                )
                coffee_product = SupplyProduct(
                    tenant_id=primary_tenant,
                    name="Молоко для кофе",
                    normalized_name="молоко для кофе",
                    default_unit_id=unit.id,
                )
                second_product = SupplyProduct(
                    id=second_product_id,
                    tenant_id=primary_tenant,
                    name="Молоко альтернативное",
                    normalized_name="молоко альтернативное",
                    default_unit_id=unit.id,
                )
                session.add_all([coffee_product, second_product])
                session.flush()
                coffee_product_id = coffee_product.id
                session.add(SupplyRequest(
                    id=old_request_id,
                    tenant_id=primary_tenant,
                    public_number=f"CTX-OLD-{old_request_id}",
                    department_id=department.id,
                    direction_id=direction.id,
                    status="DRAFT",
                    source_type="INTERNAL",
                    raw_input="молоко 1 л",
                    version=1,
                    created_by_user_id=actor_id,
                    created_at=now - timedelta(minutes=5),
                    lines=[SupplyRequestLine(
                        id=old_line_id,
                        tenant_id=primary_tenant,
                        position=1,
                        raw_text="молоко 1 л",
                    )],
                ))

            with self.sessions() as session:
                report = bootstrap_permanent_milk_context_mappings(
                    session,
                    tenant_id=primary_tenant,
                    actor_user_id=actor_id,
                )
                self.assertEqual(report.status, "CREATED")
                self.assertEqual(report.created, 3)

            with self.sessions.begin() as session:
                department = session.scalar(select(Department).where(
                    Department.tenant_id == primary_tenant,
                    Department.code == "М15",
                ))
                direction = session.scalar(select(SupplyRequestDirection).where(
                    SupplyRequestDirection.tenant_id == primary_tenant,
                    SupplyRequestDirection.code == "MAIN",
                ))
                session.add(SupplyRequest(
                    id=new_request_id,
                    tenant_id=primary_tenant,
                    public_number=f"CTX-NEW-{new_request_id}",
                    department_id=department.id,
                    direction_id=direction.id,
                    status="DRAFT",
                    source_type="INTERNAL",
                    raw_input="молоко 2 л",
                    version=1,
                    created_by_user_id=actor_id,
                    created_at=datetime.now(timezone.utc) + timedelta(seconds=1),
                    lines=[SupplyRequestLine(
                        id=new_line_id,
                        tenant_id=primary_tenant,
                        position=1,
                        raw_text="молоко 2 л",
                    )],
                ))

            with self.sessions() as session:
                old_result = recognize_supply_request(
                    session, old_request_id, expected_version=1
                )
                self.assertEqual(old_result.matched, 0)
            with self.sessions() as session:
                new_result = recognize_supply_request(
                    session, new_request_id, expected_version=1
                )
                self.assertEqual(new_result.matched, 1)
                matched = session.get(SupplyRequestLine, new_line_id)
                self.assertEqual(matched.product_id, coffee_product_id)
                self.assertEqual(matched.match_method, "CONTEXT_MAPPING")

            with self.sessions.begin() as session:
                department = session.scalar(select(Department).where(
                    Department.tenant_id == primary_tenant,
                    Department.code == "ATO",
                ))
                versioned_mapping = SupplyDepartmentProductMapping(
                    tenant_id=primary_tenant,
                    department_id=department.id,
                    phrase="версия",
                    normalized_phrase="версия",
                    product_id=coffee_product_id,
                )
                session.add(versioned_mapping)
                session.flush()
                versioned_mapping_id = versioned_mapping.id
            with self.sessions() as session:
                replaced = replace_context_mapping(
                    session,
                    mapping_id=versioned_mapping_id,
                    product_id=second_product_id,
                    expected_version=1,
                    actor_user_id=actor_id,
                )
                self.assertEqual(replaced.version, 2)
            with self.sessions() as session:
                with self.assertRaises(SupplyContextMappingVersionConflictError):
                    replace_context_mapping(
                        session,
                        mapping_id=versioned_mapping_id,
                        product_id=coffee_product_id,
                        expected_version=1,
                        actor_user_id=actor_id,
                    )
            with self.sessions() as session:
                with self.assertRaises(SupplyContextMappingVersionConflictError):
                    delete_context_mapping(
                        session,
                        mapping_id=versioned_mapping_id,
                        expected_version=1,
                        actor_user_id=actor_id,
                    )

            with self.sessions.begin() as session:
                for tenant_id in (other_tenant, conflict_tenant):
                    unit = SupplyUnit(
                        tenant_id=tenant_id,
                        code="L",
                        name_ru="Литр",
                        short_name_ru="л",
                        allows_fraction=True,
                    )
                    session.add(unit)
                    session.flush()
                    product = SupplyProduct(
                        tenant_id=tenant_id,
                        name="Молоко для кофе",
                        normalized_name="молоко для кофе",
                        default_unit_id=unit.id,
                    )
                    alternate = SupplyProduct(
                        tenant_id=tenant_id,
                        name="Другой товар",
                        normalized_name="другой товар",
                        default_unit_id=unit.id,
                    )
                    session.add_all([product, alternate])
                    session.flush()
                    for code in ("М15", "М35", "М6А"):
                        session.add(Department(
                            tenant_id=tenant_id,
                            code=code,
                            name=f"{tenant_id} {code}",
                        ))
                    session.flush()
                    if tenant_id == conflict_tenant:
                        conflict_department = session.scalar(
                            select(Department).where(
                                Department.tenant_id == tenant_id,
                                Department.code == "М15",
                            )
                        )
                        session.add(SupplyDepartmentProductMapping(
                            tenant_id=tenant_id,
                            department_id=conflict_department.id,
                            phrase="молоко",
                            normalized_phrase="молоко",
                            product_id=alternate.id,
                        ))

            with self.sessions() as session:
                selected = bootstrap_permanent_milk_context_mappings(
                    session,
                    tenant_id=other_tenant,
                    actor_user_id=actor_id,
                )
                self.assertEqual(selected.created, 3)
            with self.sessions() as session:
                self.assertEqual(session.scalar(select(func.count()).select_from(
                    SupplyDepartmentProductMapping
                ).where(
                    SupplyDepartmentProductMapping.tenant_id == conflict_tenant,
                    SupplyDepartmentProductMapping.is_permanent.is_(True),
                )), 0)
                blocked = bootstrap_permanent_milk_context_mappings(
                    session,
                    tenant_id=conflict_tenant,
                    actor_user_id=actor_id,
                )
                self.assertEqual(blocked.status, "BLOCKED")
                self.assertTrue(blocked.errors)
            with self.sessions() as session:
                missing = bootstrap_permanent_milk_context_mappings(
                    session,
                    tenant_id=f"context-missing-{tenant_suffix}",
                    actor_user_id=actor_id,
                )
                self.assertEqual(missing.status, "BLOCKED")
                self.assertEqual(missing.created, 0)
        finally:
            settings.default_tenant_id = previous_tenant_id

    def test_01e_stock_calculation_migration_cycle_with_data(self) -> None:
        if self._current_revision() == "20260804_0027":
            command.downgrade(self.alembic_config, "20260804_0026")
        else:
            command.upgrade(self.alembic_config, "20260804_0026")
        self.assertEqual(self._current_revision(), "20260804_0026")
        with self.engine.connect() as connection:
            legacy_line_id = connection.execute(text("""
                SELECT id FROM supply_request_lines
                ORDER BY created_at DESC LIMIT 1
            """)).scalar_one()

        command.upgrade(self.alembic_config, "20260804_0027")
        self.assertEqual(self._current_revision(), "20260804_0027")
        inspector = inspect(self.engine)
        self.assertTrue({
            "supply_stock_calculations",
            "supply_stock_calculation_lines",
            "supply_stock_calculation_audit_events",
        } <= set(inspector.get_table_names()))
        line_columns = {
            column["name"]: column
            for column in inspector.get_columns("supply_stock_calculation_lines")
        }
        for name in (
            "requested_quantity",
            "available_quantity",
            "transferable_quantity",
            "deficit_quantity",
        ):
            self.assertEqual(line_columns[name]["type"].precision, 18)
            self.assertEqual(line_columns[name]["type"].scale, 3)
        audit_columns = {
            column["name"]: column
            for column in inspector.get_columns(
                "supply_stock_calculation_audit_events"
            )
        }
        for name in ("previous_quantity", "quantity"):
            self.assertEqual(audit_columns[name]["type"].precision, 18)
            self.assertEqual(audit_columns[name]["type"].scale, 3)
        self.assertIn(
            "ix_supply_stock_calculation_request_revision",
            {item["name"] for item in inspector.get_indexes(
                "supply_stock_calculations"
            )},
        )
        self.assertIn(
            "ix_supply_stock_calculation_line_position",
            {item["name"] for item in inspector.get_indexes(
                "supply_stock_calculation_lines"
            )},
        )

        preliminary_id = uuid4()
        confirmed_id = uuid4()
        preliminary_line_id = uuid4()
        confirmed_line_id = uuid4()
        with self.engine.begin() as connection:
            row = connection.execute(text("""
                SELECT line.tenant_id, line.request_id, line.id AS line_id,
                       product.id AS product_id, request.created_by_user_id AS actor_id
                FROM supply_request_lines AS line
                JOIN supply_requests AS request ON request.id = line.request_id
                JOIN supply_products AS product
                  ON product.tenant_id = request.tenant_id
                WHERE line.id = :line_id
                ORDER BY product.created_at
                LIMIT 1
            """), {"line_id": legacy_line_id}).mappings().one()
            actor_id = row["actor_id"] or connection.scalar(text(
                "SELECT id FROM users ORDER BY id LIMIT 1"
            ))
            connection.execute(text("""
                INSERT INTO supply_stock_calculations
                    (id, tenant_id, request_id, revision, version, status,
                     calculated_at, calculated_by_user_id,
                     confirmed_at, confirmed_by_user_id)
                VALUES
                    (:preliminary_id, :tenant_id, :request_id, 1, 1,
                     'PRELIMINARY', now(), :actor_id, NULL, NULL),
                    (:confirmed_id, :tenant_id, :request_id, 2, 2,
                     'CONFIRMED', now(), :actor_id, now(), :actor_id)
            """), {
                **row,
                "preliminary_id": preliminary_id,
                "confirmed_id": confirmed_id,
                "actor_id": actor_id,
            })
            for calculation_id, calculation_line_id in (
                (preliminary_id, preliminary_line_id),
                (confirmed_id, confirmed_line_id),
            ):
                connection.execute(text("""
                    INSERT INTO supply_stock_calculation_lines
                        (id, tenant_id, calculation_id, request_id,
                         request_line_id, version, position, product_id,
                         product_name, unavailable_reason)
                    VALUES
                        (:id, :tenant_id, :calculation_id, :request_id,
                         :line_id, 1, 1, :product_id, 'Migration product',
                         'Migration blocked row')
                """), {
                    **row,
                    "id": calculation_line_id,
                    "calculation_id": calculation_id,
                })
            connection.execute(text("""
                INSERT INTO supply_stock_calculation_audit_events
                    (tenant_id, calculation_id, action, actor_user_id)
                VALUES
                    (:tenant_id, :preliminary_id, 'AUTO_CALCULATED', :actor_id),
                    (:tenant_id, :confirmed_id, 'CONFIRMED', :actor_id)
            """), {
                **row,
                "preliminary_id": preliminary_id,
                "confirmed_id": confirmed_id,
                "actor_id": actor_id,
            })

        command.downgrade(self.alembic_config, "20260804_0026")
        self.assertEqual(self._current_revision(), "20260804_0026")
        self.assertNotIn(
            "tenant_id",
            {column["name"] for column in inspect(self.engine).get_columns(
                "supply_request_lines"
            )},
        )
        command.upgrade(self.alembic_config, "20260804_0027")
        self.assertEqual(self._current_revision(), "20260804_0027")
        with self.engine.connect() as connection:
            self.assertIsNotNone(connection.scalar(text("""
                SELECT tenant_id FROM supply_request_lines WHERE id = :line_id
            """), {"line_id": legacy_line_id}))
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_stock_calculations"
            )), 0)

    def test_01f_stock_snapshot_migration_cycle_and_constraints(self) -> None:
        command.upgrade(self.alembic_config, "20260805_0028")
        self.assertEqual(self._current_revision(), "20260805_0028")
        inspector = inspect(self.engine)
        self.assertTrue({
            "iiko_stock_balance_snapshot_sources",
            "iiko_stock_balance_snapshot_lines",
        } <= set(inspector.get_table_names()))
        self.assertIn(
            "ix_iiko_stock_snapshot_source_latest",
            {index["name"] for index in inspector.get_indexes(
                "iiko_stock_balance_snapshot_sources"
            )},
        )
        self.assertIn(
            "ix_iiko_stock_snapshot_line_run_product",
            {index["name"] for index in inspector.get_indexes(
                "iiko_stock_balance_snapshot_lines"
            )},
        )

        command.downgrade(self.alembic_config, "20260804_0027")
        self.assertEqual(self._current_revision(), "20260804_0027")
        self.assertNotIn(
            "iiko_stock_balance_snapshot_sources",
            inspect(self.engine).get_table_names(),
        )
        command.upgrade(self.alembic_config, "20260805_0028")
        self.assertEqual(self._current_revision(), "20260805_0028")

        tenant_id = f"snapshot-{uuid4().hex[:12]}"
        department_id = uuid4()
        source_mapping_id = uuid4()
        cross_source_mapping_id = uuid4()
        warehouse_id = uuid4()
        run_id = uuid4()
        product_id = uuid4()
        unit_id = uuid4()
        snapshot_at = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.add(Department(
                id=department_id,
                tenant_id=tenant_id,
                code="SNAPSHOT",
                name="Snapshot department",
                legal_contour=LegalContour.IP,
            ))
            session.add_all([
                IikoWarehouseMapping(
                    id=source_mapping_id,
                    tenant_id=tenant_id,
                    iiko_warehouse_id=warehouse_id,
                    destination_type=IikoWarehouseDestinationType.SOURCE,
                    role=IikoWarehouseRole.MAIN,
                    legal_contour=LegalContour.IP,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="Snapshot SOURCE",
                ),
                IikoWarehouseMapping(
                    id=cross_source_mapping_id,
                    tenant_id=tenant_id,
                    iiko_warehouse_id=uuid4(),
                    destination_type=IikoWarehouseDestinationType.SOURCE,
                    role=IikoWarehouseRole.PACKAGING,
                    legal_contour=LegalContour.IP,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="Cross-tenant SOURCE",
                ),
            ])
            session.add(IikoSyncRun(
                id=run_id,
                tenant_id=tenant_id,
                sync_type=IikoSyncType.STOCK_BALANCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
                started_at=snapshot_at,
                finished_at=snapshot_at,
                parameters={},
            ))
            session.flush()
            session.add(IikoStockBalanceSnapshotSource(
                tenant_id=tenant_id,
                sync_run_id=run_id,
                department_id=department_id,
                source_warehouse_mapping_id=source_mapping_id,
                snapshot_at=snapshot_at,
                status=IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
            ))
            session.flush()
            session.add(IikoStockBalanceSnapshotLine(
                tenant_id=tenant_id,
                sync_run_id=run_id,
                department_id=department_id,
                source_warehouse_mapping_id=source_mapping_id,
                iiko_warehouse_id=warehouse_id,
                iiko_product_id=product_id,
                iiko_unit_id=unit_id,
                quantity=Decimal("-1.123456"),
                snapshot_at=snapshot_at,
            ))

        with self.engine.begin() as connection:
            duplicate_source_sql = text("""
                INSERT INTO iiko_stock_balance_snapshot_sources
                    (id, tenant_id, sync_run_id, department_id,
                     source_warehouse_mapping_id, snapshot_at, status)
                VALUES
                    (:id, :tenant_id, :run_id, :department_id,
                     :source_id, :snapshot_at, 'SUCCEEDED')
            """)
            with self.assertRaises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(duplicate_source_sql, {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "run_id": run_id,
                        "department_id": department_id,
                        "source_id": source_mapping_id,
                        "snapshot_at": snapshot_at,
                    })
            with self.assertRaises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(duplicate_source_sql, {
                        "id": uuid4(),
                        "tenant_id": f"{tenant_id}-other",
                        "run_id": run_id,
                        "department_id": department_id,
                        "source_id": cross_source_mapping_id,
                        "snapshot_at": snapshot_at,
                    })
            with self.assertRaises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text("""
                        INSERT INTO iiko_stock_balance_snapshot_lines
                            (id, tenant_id, sync_run_id, department_id,
                             source_warehouse_mapping_id, iiko_warehouse_id,
                             iiko_product_id, iiko_unit_id, quantity, snapshot_at)
                        VALUES
                            (:id, :tenant_id, :run_id, :department_id,
                             :source_id, :warehouse_id, :product_id,
                             :unit_id, 2, :snapshot_at)
                    """), {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "run_id": run_id,
                        "department_id": department_id,
                        "source_id": source_mapping_id,
                        "warehouse_id": warehouse_id,
                        "product_id": product_id,
                        "unit_id": unit_id,
                        "snapshot_at": snapshot_at,
                    })
            connection.execute(text("SET LOCAL enable_seqscan = off"))
            plan = "\n".join(connection.execute(text("""
                EXPLAIN (COSTS OFF)
                SELECT source.id
                FROM iiko_stock_balance_snapshot_sources AS source
                JOIN iiko_sync_runs AS run ON run.id = source.sync_run_id
                WHERE source.tenant_id = :tenant_id
                  AND source.source_warehouse_mapping_id = :source_id
                  AND source.status = 'SUCCEEDED'
                  AND run.tenant_id = :tenant_id
                  AND run.sync_type = 'STOCK_BALANCE_SNAPSHOT'
                  AND run.status = 'SUCCEEDED'
                  AND run.finished_at IS NOT NULL
                ORDER BY source.snapshot_at DESC, run.finished_at DESC,
                         run.started_at DESC, run.id DESC
                LIMIT 1
            """), {
                "tenant_id": tenant_id,
                "source_id": source_mapping_id,
            }).scalars())
            self.assertIn("ix_iiko_stock_snapshot_source_latest", plan)

        with self.assertRaisesRegex(
            RuntimeError,
            "Cannot downgrade while STOCK_BALANCE_SNAPSHOT runs exist",
        ):
            command.downgrade(self.alembic_config, "20260804_0027")
        self.assertEqual(self._current_revision(), "20260805_0028")
        self.assertTrue({
            "iiko_stock_balance_snapshot_sources",
            "iiko_stock_balance_snapshot_lines",
        } <= set(inspect(self.engine).get_table_names()))

        with self.sessions.begin() as session:
            session.query(IikoStockBalanceSnapshotLine).filter_by(
                sync_run_id=run_id
            ).delete(synchronize_session=False)
            session.query(IikoStockBalanceSnapshotSource).filter_by(
                sync_run_id=run_id
            ).delete(synchronize_session=False)
            session.query(IikoSyncRun).filter_by(id=run_id).delete(
                synchronize_session=False
            )
            session.query(IikoWarehouseMapping).filter_by(
                tenant_id=tenant_id
            ).delete(synchronize_session=False)
            session.query(Department).filter_by(id=department_id).delete(
                synchronize_session=False
            )
        command.downgrade(self.alembic_config, "20260804_0027")
        self.assertEqual(self._current_revision(), "20260804_0027")
        command.upgrade(self.alembic_config, "20260805_0028")
        self.assertEqual(self._current_revision(), "20260805_0028")

    def test_02_public_mutations_lock_only_supply_request_row(self) -> None:
        command.upgrade(self.alembic_config, "head")
        self.assertEqual(self._current_revision(), "20260805_0028")
        self._assert_send_quantity_schema()
        self._assert_iiko_staging_schema()
        self._assert_iiko_mapping_schema()
        self._assert_iiko_warehouse_legal_contour_schema()

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

    def test_02a_product_source_bootstrap_and_manual_do_not_deadlock(
        self,
    ) -> None:
        command.upgrade(self.alembic_config, "head")
        tenant_id = f"source-deadlock-{uuid4()}"
        first_product_id = UUID("31000000-0000-0000-0000-000000000001")
        second_product_id = UUID("31000000-0000-0000-0000-000000000002")
        actor_id, source_ids = self._seed_product_source_rows(
            tenant_id=tenant_id,
            product_ids=[first_product_id, second_product_id],
        )
        bootstrap_has_source = Event()
        manual_before_source = Event()
        thread_state = local()
        original_locked_source = source_mapping_service._locked_valid_source

        def coordinated_locked_source(*args, **kwargs):
            worker = getattr(thread_state, "worker", None)
            if worker == "bootstrap" and not getattr(
                thread_state, "source_paused", False
            ):
                source = original_locked_source(*args, **kwargs)
                thread_state.source_paused = True
                bootstrap_has_source.set()
                if not manual_before_source.wait(timeout=5):
                    raise AssertionError(
                        "Manual assignment did not reach SOURCE lock"
                    )
                return source
            if worker == "manual":
                manual_before_source.set()
            return original_locked_source(*args, **kwargs)

        def run_bootstrap():
            connection, session = self._postgres_session()
            thread_state.worker = "bootstrap"
            try:
                return bootstrap_product_source_mappings(
                    session,
                    tenant_id=tenant_id,
                    actor_user_id=actor_id,
                )
            finally:
                session.close()
                connection.close()

        def run_manual():
            if not bootstrap_has_source.wait(timeout=5):
                raise AssertionError("Bootstrap did not acquire SOURCE lock")
            connection, session = self._postgres_session()
            thread_state.worker = "manual"
            try:
                return assign_product_source(
                    session,
                    tenant_id=tenant_id,
                    product_id=second_product_id,
                    legal_contour=LegalContour.IP,
                    source_mapping_id=source_ids[0],
                    actor_user_id=actor_id,
                    expected_version=None,
                    comment=None,
                )
            finally:
                session.close()
                connection.close()

        with patch.object(
            source_mapping_service,
            "_locked_valid_source",
            side_effect=coordinated_locked_source,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                bootstrap_future = executor.submit(run_bootstrap)
                manual_future = executor.submit(run_manual)
                bootstrap_result = bootstrap_future.result(timeout=15)
                manual_result = manual_future.result(timeout=15)

        self.assertEqual(manual_result.version, 1)
        self.assertEqual(bootstrap_result.created, 1)
        self.assertEqual(bootstrap_result.already_mapped, 1)
        self.assertEqual(bootstrap_result.conflicts, 0)
        with self.sessions() as session:
            self.assertEqual(
                session.scalar(select(func.count(SupplyProductSourceMapping.id)).where(
                    SupplyProductSourceMapping.tenant_id == tenant_id
                )),
                2,
            )
            self.assertEqual(
                session.scalar(select(func.count(
                    SupplyProductSourceMappingAuditEvent.id
                )).where(
                    SupplyProductSourceMappingAuditEvent.tenant_id == tenant_id
                )),
                2,
            )

    def test_02b_product_source_concurrent_first_assignment_is_safe(
        self,
    ) -> None:
        command.upgrade(self.alembic_config, "head")
        tenant_id = f"source-first-{uuid4()}"
        product_id = UUID("32000000-0000-0000-0000-000000000001")
        actor_id, source_ids = self._seed_product_source_rows(
            tenant_id=tenant_id,
            product_ids=[product_id],
        )
        barrier = Barrier(2)

        def assign_once():
            connection, session = self._postgres_session()
            try:
                barrier.wait(timeout=5)
                try:
                    result = assign_product_source(
                        session,
                        tenant_id=tenant_id,
                        product_id=product_id,
                        legal_contour=LegalContour.IP,
                        source_mapping_id=source_ids[0],
                        actor_user_id=actor_id,
                        expected_version=None,
                        comment=None,
                    )
                    return "created", result.version
                except SupplyProductSourceVersionConflictError as error:
                    return "version_conflict", error.current_version
                except SupplyProductSourceConcurrentAssignmentError:
                    return "unique_conflict", None
            finally:
                session.close()
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=15)
                for future in [executor.submit(assign_once) for _ in range(2)]
            ]
        self.assertEqual(sum(result[0] == "created" for result in results), 1)
        self.assertEqual(
            sum(result[0] in {"version_conflict", "unique_conflict"} for result in results),
            1,
        )
        with self.sessions() as session:
            self.assertEqual(
                session.scalar(select(func.count(SupplyProductSourceMapping.id)).where(
                    SupplyProductSourceMapping.tenant_id == tenant_id
                )),
                1,
            )
            self.assertEqual(
                session.scalar(select(func.count(
                    SupplyProductSourceMappingAuditEvent.id
                )).where(
                    SupplyProductSourceMappingAuditEvent.tenant_id == tenant_id
                )),
                1,
            )

    def test_02c_product_source_stale_replacement_is_safe(self) -> None:
        command.upgrade(self.alembic_config, "head")
        tenant_id = f"source-stale-{uuid4()}"
        product_id = UUID("33000000-0000-0000-0000-000000000001")
        actor_id, source_ids = self._seed_product_source_rows(
            tenant_id=tenant_id,
            product_ids=[product_id],
            source_count=3,
        )
        with self.sessions() as session:
            initial = assign_product_source(
                session,
                tenant_id=tenant_id,
                product_id=product_id,
                legal_contour=LegalContour.IP,
                source_mapping_id=source_ids[0],
                actor_user_id=actor_id,
                expected_version=None,
                comment=None,
            )
        self.assertEqual(initial.version, 1)
        barrier = Barrier(2)

        def replace_once(source_id: UUID):
            connection, session = self._postgres_session()
            try:
                barrier.wait(timeout=5)
                try:
                    result = assign_product_source(
                        session,
                        tenant_id=tenant_id,
                        product_id=product_id,
                        legal_contour=LegalContour.IP,
                        source_mapping_id=source_id,
                        actor_user_id=actor_id,
                        expected_version=1,
                        comment="PostgreSQL concurrent replacement",
                    )
                    return "replaced", result.version
                except SupplyProductSourceVersionConflictError as error:
                    return "version_conflict", error.current_version
            finally:
                session.close()
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(replace_once, source_id)
                for source_id in source_ids[1:]
            ]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sum(result[0] == "replaced" for result in results), 1)
        self.assertEqual(sum(
            result[0] == "version_conflict" for result in results
        ), 1)
        with self.sessions() as session:
            mapping = session.scalar(select(SupplyProductSourceMapping).where(
                SupplyProductSourceMapping.tenant_id == tenant_id,
                SupplyProductSourceMapping.eos_product_id == product_id,
                SupplyProductSourceMapping.legal_contour == LegalContour.IP,
            ))
            self.assertEqual(mapping.version, 2)
            self.assertEqual(
                session.scalar(select(func.count(
                    SupplyProductSourceMappingAuditEvent.id
                )).where(
                    SupplyProductSourceMappingAuditEvent.tenant_id == tenant_id
                )),
                2,
            )

    def test_02d_stock_calculation_postgres_contracts(self) -> None:
        command.upgrade(self.alembic_config, "head")

        blocked_case = self._seed_stock_calculation_case(
            include_source_mapping=False
        )
        with self.sessions() as session:
            blocked = calculate_stock(
                session,
                tenant_id=blocked_case["tenant_id"],
                request_id=blocked_case["request_id"],
                actor_user_id=blocked_case["actor_id"],
            )
        with self.sessions() as session:
            with self.assertRaises(SupplyStockCalculationBlockedError):
                confirm_stock_calculation(
                    session,
                    tenant_id=blocked_case["tenant_id"],
                    request_id=blocked_case["request_id"],
                    calculation_id=blocked.id,
                    expected_revision=blocked.revision,
                    expected_version=blocked.version,
                    actor_user_id=blocked_case["actor_id"],
                )

        stale_case = self._seed_stock_calculation_case(quantities=(Decimal("5"),))
        with self.sessions() as session:
            first = calculate_stock(
                session,
                tenant_id=stale_case["tenant_id"],
                request_id=stale_case["request_id"],
                actor_user_id=stale_case["actor_id"],
            )
        first_line = first.groups[0].lines[0]
        with self.sessions() as session:
            updated = adjust_transferable_quantity(
                session,
                tenant_id=stale_case["tenant_id"],
                request_id=stale_case["request_id"],
                calculation_id=first.id,
                expected_revision=first.revision,
                expected_version=first.version,
                line_id=first_line.id,
                expected_line_version=first_line.version,
                quantity=Decimal("4"),
                actor_user_id=stale_case["actor_id"],
            )
        self.assertEqual(updated.version, first.version + 1)
        with self.sessions() as session:
            with self.assertRaises(SupplyStockCalculationVersionConflictError):
                adjust_transferable_quantity(
                    session,
                    tenant_id=stale_case["tenant_id"],
                    request_id=stale_case["request_id"],
                    calculation_id=first.id,
                    expected_revision=first.revision,
                    expected_version=first.version,
                    line_id=first_line.id,
                    expected_line_version=first_line.version,
                    quantity=Decimal("3"),
                    actor_user_id=stale_case["actor_id"],
                )
        with self.sessions() as session:
            second = calculate_stock(
                session,
                tenant_id=stale_case["tenant_id"],
                request_id=stale_case["request_id"],
                actor_user_id=stale_case["actor_id"],
            )
        with self.sessions() as session:
            with self.assertRaises(SupplyStockCalculationVersionConflictError):
                confirm_stock_calculation(
                    session,
                    tenant_id=stale_case["tenant_id"],
                    request_id=stale_case["request_id"],
                    calculation_id=first.id,
                    expected_revision=first.revision,
                    expected_version=updated.version,
                    actor_user_id=stale_case["actor_id"],
                )
        self.assertEqual(second.revision, first.revision + 1)

        integer_case = self._seed_stock_calculation_case(
            quantities=(Decimal("5"),), allows_fraction=False
        )
        with self.sessions() as session:
            integer_calc = calculate_stock(
                session,
                tenant_id=integer_case["tenant_id"],
                request_id=integer_case["request_id"],
                actor_user_id=integer_case["actor_id"],
            )
        integer_line = integer_calc.groups[0].lines[0]
        with self.sessions() as session:
            with self.assertRaises(SupplyStockTransferFractionInvalidError):
                adjust_transferable_quantity(
                    session,
                    tenant_id=integer_case["tenant_id"],
                    request_id=integer_case["request_id"],
                    calculation_id=integer_calc.id,
                    expected_revision=integer_calc.revision,
                    expected_version=integer_calc.version,
                    line_id=integer_line.id,
                    expected_line_version=integer_line.version,
                    quantity=Decimal("1.500"),
                    actor_user_id=integer_case["actor_id"],
                )

        tenant_a = self._seed_stock_calculation_case(quantities=(Decimal("1"),))
        tenant_b = self._seed_stock_calculation_case(quantities=(Decimal("1"),))
        with self.assertRaises(IntegrityError):
            with self.sessions.begin() as session:
                session.add(SupplyStockCalculation(
                    tenant_id=tenant_a["tenant_id"],
                    request_id=tenant_b["request_id"],
                    revision=1,
                    version=1,
                    status=SupplyStockCalculationStatus.PRELIMINARY,
                    calculated_at=datetime.now(timezone.utc),
                    calculated_by_user_id=tenant_a["actor_id"],
                ))
        with self.sessions() as session:
            tenant_a_calc = calculate_stock(
                session,
                tenant_id=tenant_a["tenant_id"],
                request_id=tenant_a["request_id"],
                actor_user_id=tenant_a["actor_id"],
            )
        tenant_a_line_id = tenant_a_calc.groups[0].lines[0].id
        cross_tenant_updates = (
            ("request_line_id", tenant_b["line_ids"][0]),
            ("product_id", tenant_b["product_id"]),
            ("requested_unit_id", tenant_b["unit_id"]),
            ("source_warehouse_mapping_id", tenant_b["source_id"]),
        )
        for column_name, foreign_id in cross_tenant_updates:
            with self.assertRaises(IntegrityError):
                with self.engine.begin() as connection:
                    connection.execute(text(
                        f"UPDATE supply_stock_calculation_lines "
                        f"SET {column_name} = :foreign_id WHERE id = :line_id"
                    ), {
                        "foreign_id": foreign_id,
                        "line_id": tenant_a_line_id,
                    })
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(text("""
                    INSERT INTO supply_stock_calculation_audit_events
                        (tenant_id, calculation_id, action, actor_user_id)
                    VALUES (:tenant_id, :calculation_id,
                            'AUTO_CALCULATED', :actor_id)
                """), {
                    "tenant_id": tenant_b["tenant_id"],
                    "calculation_id": tenant_a_calc.id,
                    "actor_id": tenant_a["actor_id"],
                })

        numeric_case = self._seed_stock_calculation_case(quantities=(Decimal("1"),))
        with self.sessions() as session:
            numeric_calc = calculate_stock(
                session,
                tenant_id=numeric_case["tenant_id"],
                request_id=numeric_case["request_id"],
                actor_user_id=numeric_case["actor_id"],
            )
        maximum = Decimal("999999999999999.999")
        with self.sessions.begin() as session:
            line = session.get(
                SupplyStockCalculationLine, numeric_calc.groups[0].lines[0].id
            )
            line.requested_quantity = maximum
            line.available_quantity = maximum
            line.transferable_quantity = maximum
            line.deficit_quantity = Decimal("0.000")
        with self.sessions() as session:
            line = session.get(
                SupplyStockCalculationLine, numeric_calc.groups[0].lines[0].id
            )
            self.assertEqual(line.transferable_quantity, maximum)

        tied_at = datetime.now(timezone.utc) + timedelta(minutes=1)
        tied_case = self._seed_stock_calculation_case(
            quantities=(Decimal("8"),),
            available=Decimal("2"),
            sync_run_id=UUID("10000000-0000-0000-0000-000000000001"),
            sync_started_at=tied_at,
            sync_finished_at=tied_at,
        )
        high_run_id = UUID("f0000000-0000-0000-0000-000000000001")
        with self.sessions.begin() as session:
            run = IikoSyncRun(
                id=high_run_id,
                tenant_id=tied_case["tenant_id"],
                sync_type=IikoSyncType.STOCK_BALANCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
                started_at=tied_at,
                finished_at=tied_at,
                parameters={
                    "snapshot_at": tied_at.isoformat(),
                    "completed_source_warehouse_mapping_ids": [str(
                        tied_case["source_id"]
                    )],
                },
            )
            session.add(run)
            session.flush()
            session.add(IikoStockBalanceSnapshotSource(
                tenant_id=tied_case["tenant_id"],
                sync_run_id=run.id,
                department_id=tied_case["department_id"],
                source_warehouse_mapping_id=tied_case["source_id"],
                snapshot_at=tied_at,
                status=IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
            ))
            session.flush()
            session.add(IikoStockBalanceSnapshotLine(
                tenant_id=tied_case["tenant_id"],
                sync_run_id=run.id,
                department_id=tied_case["department_id"],
                source_warehouse_mapping_id=tied_case["source_id"],
                iiko_warehouse_id=tied_case["warehouse_id"],
                iiko_product_id=tied_case["iiko_product_id"],
                iiko_unit_id=tied_case["iiko_unit_id"],
                quantity=Decimal("7.000"),
                snapshot_at=tied_at,
            ))
        with self.sessions() as session:
            tied_calc = calculate_stock(
                session,
                tenant_id=tied_case["tenant_id"],
                request_id=tied_case["request_id"],
                actor_user_id=tied_case["actor_id"],
            )
        self.assertEqual(
            tied_calc.groups[0].lines[0].available_quantity, Decimal("7.000")
        )

        rollback_case = self._seed_stock_calculation_case(quantities=(Decimal("2"),))

        def fail_audit_insert(_mapper, _connection, _target) -> None:
            raise RuntimeError("forced audit failure")

        event.listen(
            SupplyStockCalculationAuditEvent,
            "before_insert",
            fail_audit_insert,
        )
        try:
            with self.sessions() as session:
                with self.assertRaises(RuntimeError):
                    calculate_stock(
                        session,
                        tenant_id=rollback_case["tenant_id"],
                        request_id=rollback_case["request_id"],
                        actor_user_id=rollback_case["actor_id"],
                    )
                session.rollback()
        finally:
            event.remove(
                SupplyStockCalculationAuditEvent,
                "before_insert",
                fail_audit_insert,
            )
        with self.sessions() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(SupplyStockCalculation).where(
                    SupplyStockCalculation.tenant_id
                    == rollback_case["tenant_id"]
                )
            ), 0)

        patch_rollback_case = self._seed_stock_calculation_case(
            quantities=(Decimal("5"),)
        )
        with self.sessions() as session:
            patch_rollback_calc = calculate_stock(
                session,
                tenant_id=patch_rollback_case["tenant_id"],
                request_id=patch_rollback_case["request_id"],
                actor_user_id=patch_rollback_case["actor_id"],
            )
        patch_rollback_line = patch_rollback_calc.groups[0].lines[0]
        event.listen(
            SupplyStockCalculationAuditEvent,
            "before_insert",
            fail_audit_insert,
        )
        try:
            with self.sessions() as session:
                with self.assertRaises(RuntimeError):
                    adjust_transferable_quantity(
                        session,
                        tenant_id=patch_rollback_case["tenant_id"],
                        request_id=patch_rollback_case["request_id"],
                        calculation_id=patch_rollback_calc.id,
                        expected_revision=patch_rollback_calc.revision,
                        expected_version=patch_rollback_calc.version,
                        line_id=patch_rollback_line.id,
                        expected_line_version=patch_rollback_line.version,
                        quantity=Decimal("2"),
                        actor_user_id=patch_rollback_case["actor_id"],
                    )
                session.rollback()
        finally:
            event.remove(
                SupplyStockCalculationAuditEvent,
                "before_insert",
                fail_audit_insert,
            )
        with self.sessions() as session:
            persisted_calculation = session.get(
                SupplyStockCalculation, patch_rollback_calc.id
            )
            persisted_line = session.get(
                SupplyStockCalculationLine, patch_rollback_line.id
            )
            self.assertEqual(
                persisted_calculation.version, patch_rollback_calc.version
            )
            self.assertEqual(
                persisted_line.transferable_quantity,
                patch_rollback_line.transferable_quantity,
            )

    def test_02e_stock_calculation_postgres_concurrency(self) -> None:
        command.upgrade(self.alembic_config, "head")
        case = self._seed_stock_calculation_case()
        with self.sessions() as session:
            calculation = calculate_stock(
                session,
                tenant_id=case["tenant_id"],
                request_id=case["request_id"],
                actor_user_id=case["actor_id"],
            )
        lines = sorted(
            calculation.groups[0].lines, key=lambda item: item.position
        )

        def concurrent_adjust(line, quantity: Decimal, barrier: Barrier):
            connection, session = self._postgres_session()
            try:
                barrier.wait(timeout=5)
                try:
                    result = adjust_transferable_quantity(
                        session,
                        tenant_id=case["tenant_id"],
                        request_id=case["request_id"],
                        calculation_id=calculation.id,
                        expected_revision=calculation.revision,
                        expected_version=calculation.version,
                        line_id=line.id,
                        expected_line_version=line.version,
                        quantity=quantity,
                        actor_user_id=case["actor_id"],
                    )
                    return "updated", result.version
                except SupplyStockCalculationVersionConflictError:
                    session.rollback()
                    return "conflict", None
                except ValueError:
                    session.rollback()
                    return "invalid", None
            finally:
                session.close()
                connection.close()

        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            same_line = [
                executor.submit(
                    concurrent_adjust, lines[0], Decimal(value), barrier
                )
                for value in ("4", "5")
            ]
            same_results = [item.result(timeout=15) for item in same_line]
        self.assertEqual(sum(item[0] == "updated" for item in same_results), 1)
        self.assertEqual(sum(item[0] == "conflict" for item in same_results), 1)

        release_case = self._seed_stock_calculation_case()
        with self.sessions() as session:
            release_calc = calculate_stock(
                session,
                tenant_id=release_case["tenant_id"],
                request_id=release_case["request_id"],
                actor_user_id=release_case["actor_id"],
            )
        release_lines = sorted(
            release_calc.groups[0].lines, key=lambda item: item.position
        )
        with self.sessions() as session:
            released = adjust_transferable_quantity(
                session,
                tenant_id=release_case["tenant_id"],
                request_id=release_case["request_id"],
                calculation_id=release_calc.id,
                expected_revision=release_calc.revision,
                expected_version=release_calc.version,
                line_id=release_lines[0].id,
                expected_line_version=release_lines[0].version,
                quantity=Decimal("4"),
                actor_user_id=release_case["actor_id"],
            )
        released_lines = sorted(
            released.groups[0].lines, key=lambda item: item.position
        )
        with self.sessions() as session:
            reallocated = adjust_transferable_quantity(
                session,
                tenant_id=release_case["tenant_id"],
                request_id=release_case["request_id"],
                calculation_id=released.id,
                expected_revision=released.revision,
                expected_version=released.version,
                line_id=released_lines[1].id,
                expected_line_version=released_lines[1].version,
                quantity=Decimal("6"),
                actor_user_id=release_case["actor_id"],
            )
        self.assertEqual(sum(
            line.transferable_quantity
            for line in reallocated.groups[0].lines
        ), Decimal("10"))

        different_case = self._seed_stock_calculation_case()
        with self.sessions() as session:
            different_calc = calculate_stock(
                session,
                tenant_id=different_case["tenant_id"],
                request_id=different_case["request_id"],
                actor_user_id=different_case["actor_id"],
            )
        different_lines = sorted(
            different_calc.groups[0].lines, key=lambda item: item.position
        )

        def adjust_different(line, quantity, barrier):
            connection, session = self._postgres_session()
            try:
                barrier.wait(timeout=5)
                try:
                    adjust_transferable_quantity(
                        session,
                        tenant_id=different_case["tenant_id"],
                        request_id=different_case["request_id"],
                        calculation_id=different_calc.id,
                        expected_revision=different_calc.revision,
                        expected_version=different_calc.version,
                        line_id=line.id,
                        expected_line_version=line.version,
                        quantity=quantity,
                        actor_user_id=different_case["actor_id"],
                    )
                    return "updated"
                except SupplyStockCalculationVersionConflictError:
                    session.rollback()
                    return "conflict"
                except ValueError:
                    session.rollback()
                    return "invalid"
            finally:
                session.close()
                connection.close()

        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    adjust_different,
                    different_lines[0],
                    Decimal("4"),
                    barrier,
                ),
                executor.submit(
                    adjust_different,
                    different_lines[1],
                    Decimal("6"),
                    barrier,
                ),
            ]
            different_results = [future.result(timeout=15) for future in futures]
        self.assertIn("updated", different_results)
        with self.sessions() as session:
            persisted_lines = session.scalars(select(
                SupplyStockCalculationLine
            ).where(
                SupplyStockCalculationLine.calculation_id == different_calc.id
            )).all()
            self.assertLessEqual(sum(
                line.transferable_quantity for line in persisted_lines
            ), Decimal("10"))

        race_case = self._seed_stock_calculation_case(quantities=(Decimal("5"),))
        with self.sessions() as session:
            race_calc = calculate_stock(
                session,
                tenant_id=race_case["tenant_id"],
                request_id=race_case["request_id"],
                actor_user_id=race_case["actor_id"],
            )
        race_line = race_calc.groups[0].lines[0]

        def run_race(action: str, barrier: Barrier):
            connection, session = self._postgres_session()
            try:
                barrier.wait(timeout=5)
                try:
                    if action == "calculate":
                        result = calculate_stock(
                            session,
                            tenant_id=race_case["tenant_id"],
                            request_id=race_case["request_id"],
                            actor_user_id=race_case["actor_id"],
                        )
                    elif action == "patch":
                        result = adjust_transferable_quantity(
                            session,
                            tenant_id=race_case["tenant_id"],
                            request_id=race_case["request_id"],
                            calculation_id=race_calc.id,
                            expected_revision=race_calc.revision,
                            expected_version=race_calc.version,
                            line_id=race_line.id,
                            expected_line_version=race_line.version,
                            quantity=Decimal("4"),
                            actor_user_id=race_case["actor_id"],
                        )
                    else:
                        result = confirm_stock_calculation(
                            session,
                            tenant_id=race_case["tenant_id"],
                            request_id=race_case["request_id"],
                            calculation_id=race_calc.id,
                            expected_revision=race_calc.revision,
                            expected_version=race_calc.version,
                            actor_user_id=race_case["actor_id"],
                        )
                    return action, "ok", result.revision
                except (
                    SupplyStockCalculationVersionConflictError,
                    SupplyStockCalculationConfirmedError,
                ):
                    session.rollback()
                    return action, "conflict", None
            finally:
                session.close()
                connection.close()

        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                executor.submit(run_race, action, barrier)
                for action in ("calculate", "patch")
            ]
            calculate_patch = [future.result(timeout=15) for future in results]
        self.assertTrue(any(item[0] == "calculate" and item[1] == "ok"
                            for item in calculate_patch))

        confirm_race_case = self._seed_stock_calculation_case(
            quantities=(Decimal("5"),)
        )
        with self.sessions() as session:
            confirm_race_calc = calculate_stock(
                session,
                tenant_id=confirm_race_case["tenant_id"],
                request_id=confirm_race_case["request_id"],
                actor_user_id=confirm_race_case["actor_id"],
            )

        def calculate_or_confirm(action: str, barrier: Barrier):
            connection, session = self._postgres_session()
            try:
                barrier.wait(timeout=5)
                try:
                    if action == "calculate":
                        calculate_stock(
                            session,
                            tenant_id=confirm_race_case["tenant_id"],
                            request_id=confirm_race_case["request_id"],
                            actor_user_id=confirm_race_case["actor_id"],
                        )
                    else:
                        confirm_stock_calculation(
                            session,
                            tenant_id=confirm_race_case["tenant_id"],
                            request_id=confirm_race_case["request_id"],
                            calculation_id=confirm_race_calc.id,
                            expected_revision=confirm_race_calc.revision,
                            expected_version=confirm_race_calc.version,
                            actor_user_id=confirm_race_case["actor_id"],
                        )
                    return action, "ok"
                except (
                    SupplyStockCalculationVersionConflictError,
                    SupplyStockCalculationConfirmedError,
                ):
                    session.rollback()
                    return action, "conflict"
            finally:
                session.close()
                connection.close()

        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                executor.submit(calculate_or_confirm, action, barrier)
                for action in ("calculate", "confirm")
            ]
            calculate_confirm = [future.result(timeout=15) for future in results]
        self.assertTrue(any(item == ("calculate", "ok")
                            for item in calculate_confirm))

        double_case = self._seed_stock_calculation_case(quantities=(Decimal("5"),))
        with self.sessions() as session:
            double_calc = calculate_stock(
                session,
                tenant_id=double_case["tenant_id"],
                request_id=double_case["request_id"],
                actor_user_id=double_case["actor_id"],
            )

        def confirm_once(barrier: Barrier):
            connection, session = self._postgres_session()
            try:
                barrier.wait(timeout=5)
                try:
                    confirm_stock_calculation(
                        session,
                        tenant_id=double_case["tenant_id"],
                        request_id=double_case["request_id"],
                        calculation_id=double_calc.id,
                        expected_revision=double_calc.revision,
                        expected_version=double_calc.version,
                        actor_user_id=double_case["actor_id"],
                    )
                    return "confirmed"
                except (
                    SupplyStockCalculationVersionConflictError,
                    SupplyStockCalculationConfirmedError,
                ):
                    session.rollback()
                    return "conflict"
            finally:
                session.close()
                connection.close()

        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(confirm_once, barrier) for _ in range(2)]
            double_results = [future.result(timeout=15) for future in results]
        self.assertEqual(double_results.count("confirmed"), 1)
        self.assertEqual(double_results.count("conflict"), 1)

        calculate_case = self._seed_stock_calculation_case(
            quantities=(Decimal("5"),)
        )
        barrier = Barrier(2)

        def calculate_once():
            connection, session = self._postgres_session()
            try:
                barrier.wait(timeout=5)
                return calculate_stock(
                    session,
                    tenant_id=calculate_case["tenant_id"],
                    request_id=calculate_case["request_id"],
                    actor_user_id=calculate_case["actor_id"],
                ).revision
            finally:
                session.close()
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(calculate_once) for _ in range(2)]
            revisions = sorted(
                future.result(timeout=15) for future in futures
            )
        self.assertEqual(revisions, [1, 2])

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
            product_name = f"Редкий ингредиент EOS {uuid4().hex[:8]}"
            product = SupplyProduct(
                tenant_id="eclair",
                name=product_name,
                normalized_name=normalize_product_text(product_name),
                default_unit_id=unit.id,
            )
            session.add(product)
            session.flush()
            product_id = product.id
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
                tenant_id="eclair",
                request_id=supply_request.id,
                position=1,
                raw_text="Редкий ингредиент 3 кг",
                parsed_name="Редкий ингредиент",
                quantity=3,
                send_quantity=2,
                requested_unit_id=unit.id,
                product_id=product_id,
                match_status="MATCHED",
                match_method="MANUAL",
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
            self.assertEqual(result.status, "PLANNED")
            self.assertEqual(result.lines[0].fulfilled_total, 0)
            self.assertEqual(result.lines[0].unresolved_quantity, 3)
            self.assertIsNone(result.lines[0].active_debt_id)
            planned_version = result.version

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
            completed = client.post(
                f"/supply/requests/{request_id}/fulfill-as-planned",
                json={"expected_version": planned_version},
            )
            detail = client.get(f"/supply/requests/{request_id}")
            debts = client.get(
                "/supply/debts",
                params={
                    "status": "ACTIVE",
                    "search": "Редкий ингредиент",
                },
            )
            dashboard = client.get("/supply/summary/dashboard")
            self.assertEqual(completed.status_code, 200, completed.text)
            self.assertEqual(completed.json()["status"], "PARTIALLY_FULFILLED")
            self.assertEqual(
                completed.json()["lines"][0]["fulfilled_total"],
                "2.000",
            )
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(debts.status_code, 200, debts.text)
            self.assertEqual(dashboard.status_code, 200, dashboard.text)
            detail_line = detail.json()["lines"][0]
            debt = debts.json()["items"][0]
            self.assertEqual(detail_line["id"], str(line_id))
            self.assertEqual(detail_line["unresolved_quantity"], "1.000")
            self.assertEqual(detail_line["active_debt_quantity"], "1.000")
            self.assertEqual(debts.json()["total"], 1)
            self.assertEqual(debt["product"]["id"], str(product_id))
            self.assertEqual(debt["working_name"], product_name)
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
