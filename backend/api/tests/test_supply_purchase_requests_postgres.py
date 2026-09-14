import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.supply import (
    Department, SupplyProduct, SupplyProcurementNeed, SupplyPurchaseRequest,
    SupplyRequest, SupplyRequestDirection, SupplyRequestLine,
    SupplyStockCalculation, SupplyStockCalculationLine, SupplyUnit,
)
from app.models.user import User
from app.supply.purchase_requests import (
    collect_purchase_request_needs, get_purchase_request,
)


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplyPurchaseRequestsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql"):
            raise RuntimeError("Migration test requires PostgreSQL")
        if url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Migration test accepts only the isolated local database")
        cls.previous_database_settings = (
            settings.postgres_db, settings.postgres_user,
            settings.postgres_password, settings.postgres_host,
            settings.postgres_port,
        )
        settings.postgres_db = url.database
        settings.postgres_user = url.username or ""
        settings.postgres_password = url.password or ""
        settings.postgres_host = url.host or ""
        settings.postgres_port = url.port or 5432
        cls.engine = create_engine(TEST_DATABASE_URL)
        if inspect(cls.engine).get_table_names():
            cls.engine.dispose()
            raise RuntimeError("Migration test database must be empty")
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "previous_database_settings"):
            (
                settings.postgres_db, settings.postgres_user,
                settings.postgres_password, settings.postgres_host,
                settings.postgres_port,
            ) = cls.previous_database_settings

    def revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_migration_cycle_and_postgresql_constraints(self) -> None:
        command.upgrade(self.config, "20260907_0037")
        command.upgrade(self.config, "20260914_0038")
        self.assertEqual(self.revision(), "20260914_0038")
        command.upgrade(self.config, "20260914_0039")
        self.assertEqual(self.revision(), "20260914_0039")
        command.upgrade(self.config, "20260914_0040")
        self.assertEqual(self.revision(), "20260914_0040")
        command.upgrade(self.config, "20260914_0041")
        self.assertEqual(self.revision(), "20260914_0041")
        command.downgrade(self.config, "20260914_0040")
        self.assertEqual(self.revision(), "20260914_0040")
        command.upgrade(self.config, "20260914_0041")
        self.assertEqual(self.revision(), "20260914_0041")
        command.downgrade(self.config, "20260914_0039")
        self.assertEqual(self.revision(), "20260914_0039")
        command.upgrade(self.config, "20260914_0040")
        self.assertEqual(self.revision(), "20260914_0040")
        self.assertIn("supply_procurement_needs", inspect(self.engine).get_table_names())
        command.downgrade(self.config, "20260914_0038")
        self.assertEqual(self.revision(), "20260914_0038")
        self.assertNotIn("supply_procurement_needs", inspect(self.engine).get_table_names())
        command.downgrade(self.config, "20260907_0037")
        self.assertNotIn("supply_purchase_requests", inspect(self.engine).get_table_names())
        command.upgrade(self.config, "head")
        self.assertEqual(self.revision(), "20260914_0041")

        inspector = inspect(self.engine)
        request_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("supply_purchase_requests")
        }
        line_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("supply_purchase_request_lines")
        }
        self.assertIn(("tenant_id", "number"), request_uniques)
        self.assertIn(
            ("tenant_id", "purchase_request_id", "product_id", "unit_id"),
            line_uniques,
        )
        line_fks = {item["name"] for item in inspector.get_foreign_keys("supply_purchase_request_lines")}
        self.assertTrue({
            "fk_supply_purchase_request_lines_request_tenant",
            "fk_supply_purchase_request_lines_product_tenant",
            "fk_supply_purchase_request_lines_unit_tenant",
        }.issubset(line_fks))
        source_checks = {item["name"] for item in inspector.get_check_constraints("supply_purchase_request_line_sources")}
        self.assertTrue({
            "ck_supply_purchase_request_line_sources_type",
            "ck_supply_purchase_request_line_sources_quantity",
            "ck_supply_purchase_request_line_sources_reference",
        }.issubset(source_checks))
        source_columns = {
            item["name"] for item in inspector.get_columns(
                "supply_purchase_request_line_sources"
            )
        }
        self.assertIn("procurement_need_id", source_columns)
        self.assertNotIn("source_id", source_columns)
        source_fks = {
            item["name"] for item in inspector.get_foreign_keys(
                "supply_purchase_request_line_sources"
            )
        }
        self.assertIn(
            "fk_supply_purchase_request_line_sources_need_tenant", source_fks
        )
        source_indexes = {
            item["name"] for item in inspector.get_indexes(
                "supply_purchase_request_line_sources"
            )
        }
        self.assertIn("uq_supply_purchase_request_line_sources_need", source_indexes)
        need_checks = {
            item["name"] for item in inspector.get_check_constraints(
                "supply_procurement_needs"
            )
        }
        self.assertTrue({
            "ck_supply_procurement_needs_source_type",
            "ck_supply_procurement_needs_status",
            "ck_supply_procurement_needs_reason",
            "ck_supply_procurement_needs_source",
            "ck_supply_procurement_needs_quantity",
            "ck_supply_procurement_needs_version",
            "ck_supply_procurement_needs_closed_state",
        }.issubset(need_checks))
        need_fks = {
            item["name"] for item in inspector.get_foreign_keys(
                "supply_procurement_needs"
            )
        }
        self.assertTrue({
            "fk_supply_procurement_needs_request_line_tenant",
            "fk_supply_procurement_needs_debt_tenant",
            "fk_supply_procurement_needs_basis_line_tenant",
            "fk_supply_procurement_needs_product_tenant",
            "fk_supply_procurement_needs_unit_tenant",
            "fk_supply_procurement_needs_reserved_request_tenant",
        }.issubset(need_fks))
        need_indexes = {
            item["name"] for item in inspector.get_indexes(
                "supply_procurement_needs"
            )
        }
        self.assertTrue({
            "uq_supply_procurement_needs_open_request_line",
            "uq_supply_procurement_needs_open_debt",
            "ix_supply_procurement_needs_tenant_status_date_product_unit",
        }.issubset(need_indexes))
        allocation_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("supply_purchase_allocations")
        }
        self.assertIn(
            ("tenant_id", "purchase_request_line_id", "product_supplier_id"),
            allocation_uniques,
        )
        allocation_fks = {
            item["name"] for item in inspector.get_foreign_keys(
                "supply_purchase_allocations"
            )
        }
        self.assertTrue({
            "fk_supply_purchase_allocations_line_tenant",
            "fk_supply_purchase_allocations_relation_tenant",
            "fk_supply_purchase_allocations_unit_tenant",
        }.issubset(allocation_fks))
        allocation_checks = {
            item["name"] for item in inspector.get_check_constraints(
                "supply_purchase_allocations"
            )
        }
        self.assertTrue({
            "ck_supply_purchase_allocations_packages",
            "ck_supply_purchase_allocations_amount",
            "ck_supply_purchase_allocations_status",
        }.issubset(allocation_checks))

        unit_id, product_id, supplier_id = uuid4(), uuid4(), uuid4()
        relation_id, request_id, line_id, allocation_id = (
            uuid4(), uuid4(), uuid4(), uuid4()
        )
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) "
                "VALUES (93001, 'allocation-admin', 'Admin', 'x', 'allocation-test', true, true)"
            ))
            connection.execute(text(
                "INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) "
                "VALUES (:id, 'allocation-test', 'ALLOC_L', 'Литр', 'л', true, true)"
            ), {"id": unit_id})
            connection.execute(text(
                "INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) "
                "VALUES (:id, 'allocation-test', 'Сливки allocation', 'сливки allocation', :unit, true)"
            ), {"id": product_id, "unit": unit_id})
            connection.execute(text(
                "INSERT INTO supply_suppliers (id, tenant_id, display_name, is_active) "
                "VALUES (:id, 'allocation-test', 'Allocation Supplier', true)"
            ), {"id": supplier_id})
            connection.execute(text(
                "INSERT INTO supply_product_suppliers "
                "(id, tenant_id, product_id, supplier_id, role, priority, package_quantity, package_unit_id, price_per_package, currency, is_available, is_active) "
                "VALUES (:id, 'allocation-test', :product, :supplier, 'PRIMARY', 10, 12, :unit, 4956, 'RUB', true, true)"
            ), {"id": relation_id, "product": product_id, "supplier": supplier_id, "unit": unit_id})
            connection.execute(text(
                "INSERT INTO supply_purchase_requests "
                "(id, tenant_id, number, need_date, status, created_by_user_id) "
                "VALUES (:id, 'allocation-test', 'ZR-ALLOC-PG', CURRENT_DATE, 'READY', 93001)"
            ), {"id": request_id})
            connection.execute(text(
                "INSERT INTO supply_purchase_request_lines "
                "(id, tenant_id, purchase_request_id, product_id, quantity, unit_id, manual_future_quantity) "
                "VALUES (:id, 'allocation-test', :request, :product, 25, :unit, 25)"
            ), {"id": line_id, "request": request_id, "product": product_id, "unit": unit_id})
            connection.execute(text(
                "INSERT INTO supply_purchase_allocations "
                "(id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) "
                "VALUES (:id, 'allocation-test', :line, :relation, 36, 12, :unit, 3, 4956, 413, 'RUB', 14868, 'DRAFT')"
            ), {"id": allocation_id, "line": line_id, "relation": relation_id, "unit": unit_id})

        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO supply_purchase_allocations "
                "(id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) "
                "VALUES (:id, 'allocation-test', :line, :relation, 12, 12, :unit, 1, 4956, 413, 'RUB', 4956, 'DRAFT')"
            ), {"id": uuid4(), "line": line_id, "relation": relation_id, "unit": unit_id})
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE supply_purchase_allocations SET packages_count = 0 "
                "WHERE id = :id"
            ), {"id": allocation_id})
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO supply_purchase_allocations "
                "(id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) "
                "VALUES (:id, 'other', :line, :relation, 12, 12, :unit, 1, 4956, 413, 'RUB', 4956, 'DRAFT')"
            ), {"id": uuid4(), "line": line_id, "relation": relation_id, "unit": unit_id})

    def test_z_concurrent_collect_reserves_need_only_once(self) -> None:
        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with sessions.begin() as session:
            user = User(
                username="collector-admin", display_name="Collector Admin",
                hashed_password="x", tenant_id="tenant-a",
                is_active=True, is_admin=True,
            )
            unit = SupplyUnit(
                tenant_id="tenant-a", code="KG-COLLECT", name_ru="Килограмм",
                short_name_ru="кг", allows_fraction=True, is_active=True,
            )
            direction = SupplyRequestDirection(
                tenant_id="tenant-a", code="COLLECT", name="Collector",
                is_active=True, display_order=1,
            )
            department = Department(
                tenant_id="tenant-a", code="M15-COLLECT", name="М15",
                is_active=True, display_order=1,
            )
            session.add_all([user, unit, direction, department]); session.flush()
            product = SupplyProduct(
                tenant_id="tenant-a", name="Сахар collector",
                normalized_name="сахар collector", default_unit_id=unit.id,
                is_active=True,
            )
            source_request = SupplyRequest(
                tenant_id="tenant-a", public_number="REQ-COLLECT",
                department_id=department.id, direction_id=direction.id,
                need_date=date.today(), status="PLANNED", source_type="INTERNAL",
                raw_input="Сахар",
            )
            session.add_all([product, source_request]); session.flush()
            request_line = SupplyRequestLine(
                tenant_id="tenant-a", request_id=source_request.id, position=1,
                raw_text="Сахар", product_id=product.id,
                requested_unit_id=unit.id, quantity=Decimal("10"),
                match_status="MATCHED",
            )
            calculation = SupplyStockCalculation(
                tenant_id="tenant-a", request_id=source_request.id, revision=1,
                version=1, status="PRELIMINARY",
                calculated_at=datetime.now(timezone.utc),
            )
            session.add_all([request_line, calculation]); session.flush()
            calculation_line = SupplyStockCalculationLine(
                tenant_id="tenant-a", calculation_id=calculation.id,
                request_id=source_request.id, request_line_id=request_line.id,
                version=1, position=1, product_id=product.id,
                product_name=product.name, requested_unit_id=unit.id,
                requested_quantity=Decimal("10"), available_quantity=Decimal("0"),
                transferable_quantity=Decimal("0"), deficit_quantity=Decimal("10"),
            )
            session.add(calculation_line); session.flush()
            need = SupplyProcurementNeed(
                tenant_id="tenant-a", source_type="REQUEST_LINE",
                supply_request_line_id=request_line.id,
                basis_stock_calculation_line_id=calculation_line.id,
                product_id=product.id, unit_id=unit.id, quantity=Decimal("10"),
                need_date=date.today(), status="OPEN",
                reason="INTERNAL_STOCK_DEFICIT", version=1,
            )
            first = SupplyPurchaseRequest(
                tenant_id="tenant-a", number="ZR-CONCURRENT-A",
                need_date=date.today(), status="DRAFT", created_by_user_id=user.id,
            )
            second = SupplyPurchaseRequest(
                tenant_id="tenant-a", number="ZR-CONCURRENT-B",
                need_date=date.today(), status="DRAFT", created_by_user_id=user.id,
            )
            session.add_all([need, first, second]); session.flush()
            request_ids = (first.id, second.id)
            need_id = need.id

        barrier = Barrier(2)

        def collect(request_id):
            with sessions() as session:
                item = get_purchase_request(session, request_id, tenant_id="tenant-a")
                barrier.wait()
                return collect_purchase_request_needs(session, item).line_count

        with ThreadPoolExecutor(max_workers=2) as executor:
            counts = list(executor.map(collect, request_ids))
        self.assertEqual(sorted(counts), [0, 1])
        with sessions() as session:
            reserved = session.get(SupplyProcurementNeed, need_id)
            self.assertIn(reserved.reserved_purchase_request_id, request_ids)


if __name__ == "__main__":
    unittest.main()
