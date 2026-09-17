import os
import unittest
from concurrent.futures import ThreadPoolExecutor
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
from app.schemas.purchase_allocation import SupplyPurchaseAllocationSourceWrite
from app.schemas.supplier_acceptance import (
    SupplySupplierAcceptanceCreate,
    SupplySupplierAcceptanceLineUpdate,
)
from app.supply.purchase_allocations import (
    PurchaseAllocationStateError,
    confirm_purchase_allocation,
    update_purchase_allocation_sources,
)
from app.supply.supplier_acceptances import (
    SupplierAcceptanceConflictError,
    create_acceptance,
    record_acceptance,
    update_line,
)
from app.supply.supplier_orders import create_supplier_orders


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplyQuantityTraceabilityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        url = make_url(TEST_DATABASE_URL)
        if (
            not url.drivername.startswith("postgresql")
            or url.host not in ALLOWED_HOSTS
            or url.database != EXPECTED_DATABASE_NAME
        ):
            raise RuntimeError("Migration test accepts only local eos_supply_migration_test")
        cls.previous_settings = (
            settings.postgres_db, settings.postgres_user, settings.postgres_password,
            settings.postgres_host, settings.postgres_port,
        )
        settings.postgres_db, settings.postgres_user = url.database, url.username or ""
        settings.postgres_password, settings.postgres_host = url.password or "", url.host or ""
        settings.postgres_port = url.port or 5432
        cls.engine = create_engine(TEST_DATABASE_URL)
        if inspect(cls.engine).get_table_names():
            raise RuntimeError("Migration test database must be empty")
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        (
            settings.postgres_db, settings.postgres_user, settings.postgres_password,
            settings.postgres_host, settings.postgres_port,
        ) = cls.previous_settings

    def revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_cycle_legacy_backfill_constraints_and_allocation_concurrency(self) -> None:
        command.upgrade(self.config, "20260917_0053")
        tenant = "trace-pg"
        unit_id, product_id = uuid4(), uuid4()
        supplier_a, supplier_b = uuid4(), uuid4()
        relation_a, relation_b = uuid4(), uuid4()
        single_request, multi_request, request_id = uuid4(), uuid4(), uuid4()
        single_line, multi_line, concurrent_line = uuid4(), uuid4(), uuid4()
        single_source, multi_a, multi_b, concurrent_source = (
            uuid4(), uuid4(), uuid4(), uuid4()
        )
        single_allocation, multi_allocation = uuid4(), uuid4()
        concurrent_a, concurrent_b = uuid4(), uuid4()
        order_id, order_line_id = uuid4(), uuid4()
        acceptance_id, acceptance_line_id = uuid4(), uuid4()
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) "
                "VALUES (95401, 'trace-admin', 'Trace Admin', 'x', :tenant, true, true)"
            ), {"tenant": tenant})
            connection.execute(text(
                "INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) "
                "VALUES (:id, :tenant, 'TRACE_KG', 'Килограмм', 'кг', true, true)"
            ), {"id": unit_id, "tenant": tenant})
            connection.execute(text(
                "INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) "
                "VALUES (:id, :tenant, 'Сахар trace', 'сахар trace', :unit, true)"
            ), {"id": product_id, "tenant": tenant, "unit": unit_id})
            for supplier_id, name in ((supplier_a, "Trace A"), (supplier_b, "Trace B")):
                connection.execute(text(
                    "INSERT INTO supply_suppliers (id, tenant_id, display_name, is_active) "
                    "VALUES (:id, :tenant, :name, true)"
                ), {"id": supplier_id, "tenant": tenant, "name": name})
            for relation_id, supplier_id, role in (
                (relation_a, supplier_a, "PRIMARY"),
                (relation_b, supplier_b, "BACKUP"),
            ):
                connection.execute(text(
                    "INSERT INTO supply_product_suppliers "
                    "(id, tenant_id, product_id, supplier_id, role, priority, package_quantity, package_unit_id, price_per_package, currency, is_available, is_active) "
                    "VALUES (:id, :tenant, :product, :supplier, :role, 10, 1, :unit, 10, 'RUB', true, true)"
                ), {"id": relation_id, "tenant": tenant, "product": product_id,
                    "supplier": supplier_id, "role": role, "unit": unit_id})
            for next_request, number in (
                (single_request, "ZR-TRACE-SINGLE"),
                (multi_request, "ZR-TRACE-MULTI"),
                (request_id, "ZR-TRACE-CONCURRENT"),
            ):
                connection.execute(text(
                    "INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) "
                    "VALUES (:id, :tenant, :number, CURRENT_DATE, 'READY', 95401)"
                ), {"id": next_request, "tenant": tenant, "number": number})
            for line_id, line_request, quantity in (
                (single_line, single_request, 30),
                (multi_line, multi_request, 70),
                (concurrent_line, request_id, 100),
            ):
                connection.execute(text(
                    "INSERT INTO supply_purchase_request_lines "
                    "(id, tenant_id, purchase_request_id, product_id, quantity, unit_id, manual_future_quantity) "
                    "VALUES (:id, :tenant, :request, :product, :quantity, :unit, :quantity)"
                ), {"id": line_id, "tenant": tenant, "request": line_request,
                    "product": product_id, "quantity": quantity, "unit": unit_id})
            for source_id, line_id, quantity in (
                (single_source, single_line, 30),
                (multi_a, multi_line, 30), (multi_b, multi_line, 40),
                (concurrent_source, concurrent_line, 100),
            ):
                connection.execute(text(
                    "INSERT INTO supply_purchase_request_line_sources "
                    "(id, tenant_id, purchase_request_line_id, source_type, procurement_need_id, quantity, unit_id) "
                    "VALUES (:id, :tenant, :line, 'MANUAL_FUTURE', NULL, :quantity, :unit)"
                ), {"id": source_id, "tenant": tenant, "line": line_id,
                    "quantity": quantity, "unit": unit_id})
            for allocation_id, line_id, relation_id, quantity, status in (
                (single_allocation, single_line, relation_a, 32, "CONFIRMED"),
                (multi_allocation, multi_line, relation_a, 72, "CONFIRMED"),
                (concurrent_a, concurrent_line, relation_a, 60, "DRAFT"),
                (concurrent_b, concurrent_line, relation_b, 60, "DRAFT"),
            ):
                connection.execute(text(
                    "INSERT INTO supply_purchase_allocations "
                    "(id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) "
                    "VALUES (:id, :tenant, :line, :relation, :quantity, 1, :unit, :quantity, 10, 10, 'RUB', :amount, :status)"
                ), {"id": allocation_id, "tenant": tenant, "line": line_id,
                    "relation": relation_id, "quantity": quantity, "unit": unit_id,
                    "amount": quantity * 10, "status": status})
            connection.execute(text(
                "INSERT INTO supply_supplier_orders "
                "(id, tenant_id, number, supplier_id, purchase_request_id, status, total_amount, currency, created_by_user_id, confirmed_at, sent_at) "
                "VALUES (:id, :tenant, 'PO-TRACE-PG', :supplier, :request, 'SENT', 320, 'RUB', 95401, now(), now())"
            ), {"id": order_id, "tenant": tenant, "supplier": supplier_a,
                "request": single_request})
            connection.execute(text(
                "INSERT INTO supply_supplier_order_lines "
                "(id, tenant_id, supplier_order_id, source_allocation_id, product_id, product_name_snapshot, packages_count, package_quantity_snapshot, package_unit_id_snapshot, quantity_base, price_per_package_snapshot, base_unit_price_snapshot, planned_amount, currency, is_active_owner) "
                "VALUES (:id, :tenant, :order_id, :allocation, :product, 'Сахар trace', 32, 1, :unit, 32, 10, 10, 320, 'RUB', true)"
            ), {"id": order_line_id, "tenant": tenant, "order_id": order_id,
                "allocation": single_allocation, "product": product_id, "unit": unit_id})
            connection.execute(text(
                "INSERT INTO supply_supplier_acceptances "
                "(id, tenant_id, supplier_order_id, status, recorded_by_user_id, recorded_at, created_by_user_id) "
                "VALUES (:id, :tenant, :order_id, 'RECORDED', 95401, now(), 95401)"
            ), {"id": acceptance_id, "tenant": tenant, "order_id": order_id})
            connection.execute(text(
                "INSERT INTO supply_supplier_acceptance_lines "
                "(id, tenant_id, acceptance_id, supplier_order_id, supplier_order_line_id, product_name_snapshot, product_id, unit_id, unit_name_snapshot, received_quantity, accepted_quantity, rejected_quantity, currency) "
                "VALUES (:id, :tenant, :acceptance, :order_id, :order_line, 'Сахар trace', :product, :unit, 'кг', 30, 30, 0, 'RUB')"
            ), {"id": acceptance_line_id, "tenant": tenant,
                "acceptance": acceptance_id, "order_id": order_id,
                "order_line": order_line_id, "product": product_id, "unit": unit_id})

        command.upgrade(self.config, "20260917_0054")
        self.assertEqual(self.revision(), "20260917_0054")
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_purchase_allocation_sources WHERE allocation_id=:id"
            ), {"id": single_allocation}), 1)
            self.assertEqual(connection.scalar(text(
                "SELECT allocated_quantity FROM supply_purchase_allocation_sources WHERE allocation_id=:id"
            ), {"id": single_allocation}), Decimal("30.000000"))
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_purchase_allocation_sources WHERE allocation_id=:id"
            ), {"id": multi_allocation}), 0)
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_supplier_order_line_sources WHERE order_line_id=:id"
            ), {"id": order_line_id}), 1)
            self.assertEqual(connection.scalar(text(
                "SELECT count(*) FROM supply_supplier_acceptance_line_sources WHERE acceptance_line_id=:id"
            ), {"id": acceptance_line_id}), 1)

        inspector = inspect(self.engine)
        self.assertTrue({
            "supply_purchase_allocation_sources",
            "supply_supplier_order_line_sources",
            "supply_supplier_acceptance_line_sources",
        }.issubset(inspector.get_table_names()))
        self.assertIn(
            "ck_supply_purchase_allocation_sources_quantity",
            {row["name"] for row in inspector.get_check_constraints("supply_purchase_allocation_sources")},
        )
        self.assertIn(
            "uq_supply_supplier_acceptance_line_sources_pair",
            {row["name"] for row in inspector.get_unique_constraints("supply_supplier_acceptance_line_sources")},
        )
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO supply_purchase_allocation_sources "
                "(id, tenant_id, allocation_id, purchase_request_line_source_id, allocated_quantity) "
                "VALUES (:id, :tenant, :allocation, :source, 0)"
            ), {"id": uuid4(), "tenant": tenant, "allocation": concurrent_a,
                "source": concurrent_source})

        command.downgrade(self.config, "20260917_0053")
        self.assertEqual(self.revision(), "20260917_0053")
        command.upgrade(self.config, "20260917_0054")
        self.assertEqual(self.revision(), "20260917_0054")

        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        for allocation_id in (concurrent_a, concurrent_b):
            with sessions() as session:
                update_purchase_allocation_sources(
                    session, request_id, concurrent_line, allocation_id,
                    [SupplyPurchaseAllocationSourceWrite(
                        purchase_request_line_source_id=concurrent_source,
                        allocated_quantity=Decimal("60"),
                    )], tenant_id=tenant,
                )

        barrier = Barrier(2)
        def confirm(allocation_id):
            with sessions() as session:
                barrier.wait()
                try:
                    confirm_purchase_allocation(
                        session, request_id, concurrent_line, allocation_id,
                        tenant_id=tenant,
                    )
                    return "CONFIRMED"
                except PurchaseAllocationStateError:
                    return "CONFLICT"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in (
                pool.submit(confirm, concurrent_a), pool.submit(confirm, concurrent_b),
            )]
        self.assertEqual(results.count("CONFIRMED"), 1)
        self.assertEqual(results.count("CONFLICT"), 1)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text(
                "SELECT sum(s.allocated_quantity) "
                "FROM supply_purchase_allocation_sources s "
                "JOIN supply_purchase_allocations a ON a.id=s.allocation_id "
                "WHERE s.purchase_request_line_source_id=:source AND a.status='CONFIRMED'"
            ), {"source": concurrent_source}), Decimal("60.000000"))

        department_id, destination_id = uuid4(), uuid4()
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO departments (id, tenant_id, code, name, legal_contour, is_active, display_order) "
                "VALUES (:id, :tenant, 'TRACE', 'Trace Department', 'IP', true, 1)"
            ), {"id": department_id, "tenant": tenant})
            connection.execute(text(
                "INSERT INTO iiko_warehouse_mappings "
                "(id, tenant_id, iiko_warehouse_id, eos_department_id, destination_type, role, status, source_name, is_deleted, reasons) "
                "VALUES (:id, :tenant, :warehouse, :department, 'DESTINATION', 'MAIN', 'CONFIRMED', 'Trace Store', false, CAST('[]' AS JSONB))"
            ), {"id": destination_id, "tenant": tenant, "warehouse": uuid4(),
                "department": department_id})
        with sessions() as session:
            order = create_supplier_orders(
                session, request_id, tenant_id=tenant, user_id=95401,
            )[0]
            order_id = order.id
        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE supply_supplier_orders SET status='SENT', confirmed_at=now(), sent_at=now() WHERE id=:id"
            ), {"id": order_id})
        acceptance_ids = []
        for _ in range(2):
            with sessions() as session:
                acceptance = create_acceptance(
                    session, order_id,
                    SupplySupplierAcceptanceCreate(
                        destination_mapping_id=destination_id,
                    ), tenant_id=tenant, user_id=95401,
                )
                line_id = acceptance.lines[0].id
                update_line(
                    session, acceptance.id, line_id,
                    SupplySupplierAcceptanceLineUpdate(
                        received_quantity=Decimal("40"),
                        accepted_quantity=Decimal("40"),
                        rejected_quantity=Decimal("0"),
                    ), tenant_id=tenant,
                )
                acceptance_ids.append(acceptance.id)

        acceptance_barrier = Barrier(2)
        def record(identifier):
            with sessions() as session:
                acceptance_barrier.wait()
                try:
                    record_acceptance(
                        session, identifier, tenant_id=tenant, user_id=95401,
                    )
                    return "RECORDED"
                except SupplierAcceptanceConflictError:
                    return "CONFLICT"

        with ThreadPoolExecutor(max_workers=2) as pool:
            acceptance_results = [future.result(timeout=15) for future in (
                pool.submit(record, acceptance_ids[0]),
                pool.submit(record, acceptance_ids[1]),
            )]
        self.assertEqual(acceptance_results.count("RECORDED"), 1)
        self.assertEqual(acceptance_results.count("CONFLICT"), 1)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text(
                "SELECT sum(f.accepted_quantity) "
                "FROM supply_supplier_acceptance_line_sources f "
                "JOIN supply_supplier_acceptance_lines l ON l.id=f.acceptance_line_id "
                "JOIN supply_supplier_acceptances a ON a.id=l.acceptance_id "
                "WHERE a.status='RECORDED' AND l.supplier_order_id=:order"
            ), {"order": order_id}), Decimal("40.000000"))


if __name__ == "__main__":
    unittest.main()
