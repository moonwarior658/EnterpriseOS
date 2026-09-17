import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.supply import (
    SupplySupplierConfirmation, SupplySupplierConfirmationDeviation,
    SupplySupplierConfirmationLine, SupplySupplierOrder,
)
from app.schemas.supplier_confirmation import SupplySupplierConfirmationDecisionCreate
from app.supply.supplier_confirmations import (
    SupplierConfirmationDecisionConflictError, create_confirmation, decide_deviation,
    record_confirmation,
)


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplySupplierConfirmationsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_DATABASE_URL is None:
            raise RuntimeError("Test database URL is required")
        url = make_url(TEST_DATABASE_URL)
        if not url.drivername.startswith("postgresql") or url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Migration test accepts only local eos_supply_migration_test")
        cls.previous_settings = (settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port)
        settings.postgres_db, settings.postgres_user = url.database, url.username or ""
        settings.postgres_password, settings.postgres_host = url.password or "", url.host or ""
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
        if hasattr(cls, "previous_settings"):
            settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port = cls.previous_settings

    def revision(self) -> str | None:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_cycle_constraints_tenant_fk_concurrency_and_locking(self) -> None:
        command.upgrade(self.config, "20260915_0045")
        command.upgrade(self.config, "20260917_0046")
        command.upgrade(self.config, "20260917_0047")
        self.assertEqual(self.revision(), "20260917_0047")
        command.downgrade(self.config, "20260917_0046")
        self.assertEqual(self.revision(), "20260917_0046")
        command.upgrade(self.config, "20260917_0047")

        inspector = inspect(self.engine)
        indexes = {item["name"]: item for item in inspector.get_indexes("supply_supplier_confirmations")}
        self.assertTrue(indexes["uq_supply_supplier_confirmations_draft"]["unique"])
        self.assertTrue(indexes["uq_supply_supplier_confirmations_current"]["unique"])
        self.assertIn("fk_supply_supplier_confirmation_lines_order_line_tenant", {
            item["name"] for item in inspector.get_foreign_keys("supply_supplier_confirmation_lines")
        })
        deviation_indexes = {
            item["name"]: item
            for item in inspector.get_indexes("supply_supplier_confirmation_deviations")
        }
        self.assertTrue(deviation_indexes["uq_supply_confirmation_deviations_line_type"]["unique"])
        self.assertTrue(deviation_indexes["uq_supply_confirmation_deviations_header_type"]["unique"])

        unit_id, product_id, supplier_id, relation_id = uuid4(), uuid4(), uuid4(), uuid4()
        request_id, request_line_id, allocation_id, order_id, order_line_id = (uuid4() for _ in range(5))
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) VALUES (94601, 'confirmation-admin', 'Admin', 'x', 'confirmation-test', true, true)"))
            connection.execute(text("INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) VALUES (:id, 'confirmation-test', 'CONF_KG', 'Килограмм', 'кг', true, true)"), {"id": unit_id})
            connection.execute(text("INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) VALUES (:id, 'confirmation-test', 'Сахар confirm', 'сахар confirm', :unit, true)"), {"id": product_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_suppliers (id, tenant_id, display_name, is_active) VALUES (:id, 'confirmation-test', 'Confirmation Supplier', true)"), {"id": supplier_id})
            connection.execute(text("INSERT INTO supply_product_suppliers (id, tenant_id, product_id, supplier_id, role, priority, package_quantity, package_unit_id, price_per_package, currency, is_available, is_active) VALUES (:id, 'confirmation-test', :product, :supplier, 'PRIMARY', 10, 12, :unit, 100, 'RUB', true, true)"), {"id": relation_id, "product": product_id, "supplier": supplier_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) VALUES (:id, 'confirmation-test', 'ZR-CONFIRM-PG', CURRENT_DATE, 'READY', 94601)"), {"id": request_id})
            connection.execute(text("INSERT INTO supply_purchase_request_lines (id, tenant_id, purchase_request_id, product_id, quantity, unit_id, manual_future_quantity) VALUES (:id, 'confirmation-test', :request, :product, 24, :unit, 24)"), {"id": request_line_id, "request": request_id, "product": product_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_purchase_allocations (id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) VALUES (:id, 'confirmation-test', :line, :relation, 24, 12, :unit, 2, 100, 8.333333, 'RUB', 200, 'CONFIRMED')"), {"id": allocation_id, "line": request_line_id, "relation": relation_id, "unit": unit_id})
            connection.execute(text("INSERT INTO supply_supplier_orders (id, tenant_id, number, supplier_id, purchase_request_id, status, planned_delivery_date, total_amount, currency, created_by_user_id, confirmed_at, sent_at) VALUES (:id, 'confirmation-test', 'PO-CONFIRM-PG', :supplier, :request, 'SENT', CURRENT_DATE, 200, 'RUB', 94601, now(), now())"), {"id": order_id, "supplier": supplier_id, "request": request_id})
            connection.execute(text("INSERT INTO supply_supplier_order_lines (id, tenant_id, supplier_order_id, source_allocation_id, product_id, product_name_snapshot, packages_count, package_quantity_snapshot, package_unit_id_snapshot, quantity_base, price_per_package_snapshot, base_unit_price_snapshot, planned_amount, currency, is_active_owner) VALUES (:id, 'confirmation-test', :order, :allocation, :product, 'Сахар confirm', 2, 12, :unit, 24, 100, 8.333333, 200, 'RUB', true)"), {"id": order_line_id, "order": order_id, "allocation": allocation_id, "product": product_id, "unit": unit_id})

        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        barrier = Barrier(2)
        def create_draft() -> str:
            with sessions() as session:
                barrier.wait()
                return str(create_confirmation(session, order_id, tenant_id="confirmation-test", user_id=94601).id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = [future.result(timeout=15) for future in (pool.submit(create_draft), pool.submit(create_draft))]
        self.assertEqual(ids[0], ids[1])
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM supply_supplier_confirmations WHERE status='DRAFT'")), 1)

        statements: list[str] = []
        def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", capture_sql)
        try:
            with sessions() as session:
                recorded = record_confirmation(session, UUID(ids[0]), tenant_id="confirmation-test", user_id=94601)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture_sql)
        self.assertEqual(recorded.status, "RECORDED")
        self.assertEqual(recorded.deviations, [])
        locking = [statement for statement in statements if "FOR UPDATE" in statement.upper() and "supply_supplier_orders" in statement]
        self.assertTrue(locking)
        self.assertTrue(any("FOR UPDATE OF supply_supplier_orders" in statement for statement in locking))

        revision_barrier = Barrier(2)
        def create_next_revision() -> tuple[str, int]:
            with sessions() as session:
                revision_barrier.wait()
                value = create_confirmation(session, order_id, tenant_id="confirmation-test", user_id=94601)
                return str(value.id), value.revision_number
        with ThreadPoolExecutor(max_workers=2) as pool:
            revisions = [future.result(timeout=15) for future in (
                pool.submit(create_next_revision), pool.submit(create_next_revision)
            )]
        self.assertEqual(revisions[0], revisions[1])
        self.assertEqual(revisions[0][1], 2)

        revision_two_id = UUID(revisions[0][0])
        with sessions.begin() as session:
            line = session.scalar(select(SupplySupplierConfirmationLine).where(
                SupplySupplierConfirmationLine.confirmation_id == revision_two_id,
            ))
            line.response_status = "CHANGED"
            line.confirmed_packages_count = 1
            line.confirmed_quantity_base = 12
            line.confirmed_price_per_package = 120
            line.confirmed_planned_amount = 120
        with sessions() as session:
            revision_two = record_confirmation(
                session, revision_two_id, tenant_id="confirmation-test", user_id=94601,
            )
        self.assertEqual(
            {item.deviation_type for item in revision_two.deviations},
            {"QUANTITY_CHANGED", "PRICE_CHANGED"},
        )
        deviation_id = next(
            item.id for item in revision_two.deviations
            if item.deviation_type == "QUANTITY_CHANGED"
        )

        decision_barrier = Barrier(2)
        def decide(value: str) -> str:
            with sessions() as session:
                decision_barrier.wait()
                try:
                    decide_deviation(
                        session, deviation_id,
                        SupplySupplierConfirmationDecisionCreate(decision=value),
                        tenant_id="confirmation-test", user_id=94601,
                    )
                    return "ok"
                except SupplierConfirmationDecisionConflictError:
                    return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in (
                pool.submit(decide, "ACCEPT"), pool.submit(decide, "REJECT")
            )]
        self.assertEqual(sorted(results), ["conflict", "ok"])

        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO supply_supplier_confirmation_deviations "
                "(id, tenant_id, confirmation_id, confirmation_line_id, supplier_order_line_id, "
                "deviation_type, requires_decision, status) "
                "SELECT :id, tenant_id, confirmation_id, confirmation_line_id, supplier_order_line_id, "
                "deviation_type, requires_decision, 'OPEN' "
                "FROM supply_supplier_confirmation_deviations WHERE id = :source"
            ), {"id": uuid4(), "source": deviation_id})

        with sessions() as session:
            revision_three = create_confirmation(
                session, order_id, tenant_id="confirmation-test", user_id=94601,
            )
        with patch(
            "app.supply.supplier_confirmations.generate_deviations",
            side_effect=RuntimeError("synthetic deviation failure"),
        ):
            with sessions() as session, self.assertRaises(RuntimeError):
                record_confirmation(
                    session, revision_three.id, tenant_id="confirmation-test", user_id=94601,
                )
        with sessions() as session:
            stored = session.get(SupplySupplierConfirmation, revision_three.id)
            current = session.scalar(select(SupplySupplierConfirmation).where(
                SupplySupplierConfirmation.supplier_order_id == order_id,
                SupplySupplierConfirmation.status == "RECORDED",
            ))
            self.assertEqual(stored.status, "DRAFT")
            self.assertEqual(current.id, revision_two_id)

        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("INSERT INTO supply_supplier_confirmations (id, tenant_id, supplier_order_id, revision_number, status, created_by_user_id) VALUES (:id, 'confirmation-test', :order, 1, 'DRAFT', 94601)"), {"id": uuid4(), "order": order_id})
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("INSERT INTO supply_supplier_confirmations (id, tenant_id, supplier_order_id, revision_number, status, response_type, recorded_at, created_by_user_id) VALUES (:id, 'confirmation-test', :order, 3, 'RECORDED', 'CONFIRMED', now(), 94601)"), {"id": uuid4(), "order": order_id})
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("INSERT INTO supply_supplier_confirmation_lines (id, tenant_id, confirmation_id, supplier_order_line_id, response_status, product_name_snapshot, currency) VALUES (:id, 'other-tenant', :confirmation, :line, 'REJECTED', 'x', 'RUB')"), {"id": uuid4(), "confirmation": UUID(ids[0]), "line": order_line_id})


if __name__ == "__main__":
    unittest.main()
