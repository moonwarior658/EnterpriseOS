import asyncio
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.integrations.iiko.schemas import (
    IikoDocumentValidationResultDto,
    IikoIncomingInvoiceDto,
    IikoIncomingInvoiceItemDto,
    IikoIncomingInvoiceStatus,
)
from app.supply.iiko_incoming_receipts import (
    IncomingReceiptStateError,
    _finalize_posted,
    create_receipt,
    mark_receipt_ready,
    prepare_receipt,
    process_receipt,
)


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


class FakeProvider:
    def __init__(self):
        self.lock = Lock()
        self.create_calls = 0
        self.process_calls = 0
        self.stock_calls = 0
        self.fail_stock_refresh = False
        self.document_id = uuid4()
        self.current_status = IikoIncomingInvoiceStatus.NEW
        self.preview = None

    def invoice(self):
        value = self.preview
        if value is None:
            return None
        return IikoIncomingInvoiceDto(
            external_id=self.document_id,
            document_number=value.document_number,
            status=self.current_status,
            supplier_id=value.supplier_id,
            default_store_id=value.default_store_id,
            items=tuple(IikoIncomingInvoiceItemDto(
                product_id=line.product_id,
                store_id=line.store_id,
                amount=line.amount,
                amount_unit=line.amount_unit_id,
                price=line.price,
                sum_amount=line.sum_amount,
            ) for line in value.items),
        )

    async def create_incoming_invoice(self, document):
        with self.lock:
            self.create_calls += 1
            self.preview = document
        return IikoDocumentValidationResultDto(
            valid=True, warning=False, document_number=document.document_number
        )

    async def get_incoming_invoices(self, **_kwargs):
        value = self.invoice()
        return [] if value is None else [value]

    async def get_incoming_invoice_by_id(self, *_args, **_kwargs):
        return self.invoice()

    async def process_incoming_invoice(self, _document_id):
        with self.lock:
            self.process_calls += 1
            self.current_status = IikoIncomingInvoiceStatus.PROCESSED
        return IikoDocumentValidationResultDto(
            valid=True, warning=False, document_number=self.preview.document_number
        )

    async def get_stock_balances(self, **_kwargs):
        with self.lock:
            self.stock_calls += 1
        if self.fail_stock_refresh:
            raise TimeoutError("stock refresh unavailable")
        return []


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class IikoIncomingReceiptsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_DATABASE_URL)
        if (
            not url.drivername.startswith("postgresql")
            or url.host not in ALLOWED_HOSTS
            or url.database != EXPECTED_DATABASE_NAME
        ):
            raise RuntimeError("Receipt test accepts only local eos_supply_migration_test")
        cls.previous_settings = (
            settings.postgres_db, settings.postgres_user,
            settings.postgres_password, settings.postgres_host,
            settings.postgres_port,
        )
        settings.postgres_db, settings.postgres_user = url.database, url.username or ""
        settings.postgres_password, settings.postgres_host = url.password or "", url.host or ""
        settings.postgres_port = url.port or 5432
        cls.engine = create_engine(TEST_DATABASE_URL)
        if inspect(cls.engine).get_table_names():
            cls.engine.dispose()
            raise RuntimeError("Receipt migration test database must be empty")
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        (
            settings.postgres_db, settings.postgres_user,
            settings.postgres_password, settings.postgres_host,
            settings.postgres_port,
        ) = cls.previous_settings

    def revision(self):
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def seed(self):
        ids = {name: uuid4() for name in (
            "department", "destination", "unit", "product", "supplier", "relation",
            "request", "request_line", "allocation", "order", "order_line",
            "document", "document_line", "acceptance", "acceptance_line",
            "supplier_mapping", "product_mapping", "unit_mapping",
        )}
        ids.update(iiko_store=uuid4(), iiko_supplier=uuid4(), iiko_product=uuid4(), iiko_unit=uuid4())
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO users (id, username, display_name, hashed_password, tenant_id, is_active, is_admin) VALUES (95601, 'receipt-admin', 'Admin', 'x', 'receipt-test', true, true)"))
            c.execute(text("INSERT INTO departments (id, tenant_id, code, name, legal_contour, is_active, display_order) VALUES (:id, 'receipt-test', 'REC', 'Receipt Department', 'OOO', true, 1)"), {"id": ids["department"]})
            c.execute(text("INSERT INTO iiko_warehouse_mappings (id, tenant_id, iiko_warehouse_id, eos_department_id, destination_type, role, status, source_name, is_deleted, reasons) VALUES (:id, 'receipt-test', :external, :department, 'DESTINATION', 'MAIN', 'CONFIRMED', 'Receipt Store', false, CAST('[]' AS JSONB))"), {"id": ids["destination"], "external": ids["iiko_store"], "department": ids["department"]})
            c.execute(text("INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) VALUES (:id, 'receipt-test', 'REC_KG', 'Килограмм', 'кг', true, true)"), {"id": ids["unit"]})
            c.execute(text("INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) VALUES (:id, 'receipt-test', 'Receipt product', 'receipt product', :unit, true)"), {"id": ids["product"], "unit": ids["unit"]})
            c.execute(text("INSERT INTO supply_suppliers (id, tenant_id, display_name, inn, kpp, is_active) VALUES (:id, 'receipt-test', 'МЕГАПРОД ООО', '9715495301', '771501001', true)"), {"id": ids["supplier"]})
            c.execute(text("INSERT INTO supply_product_suppliers (id, tenant_id, product_id, supplier_id, role, priority, package_quantity, package_unit_id, price_per_package, currency, is_available, is_active) VALUES (:id, 'receipt-test', :product, :supplier, 'PRIMARY', 1, 1, :unit, 50, 'RUB', true, true)"), {"id": ids["relation"], "product": ids["product"], "supplier": ids["supplier"], "unit": ids["unit"]})
            c.execute(text("INSERT INTO supply_purchase_requests (id, tenant_id, number, need_date, status, created_by_user_id) VALUES (:id, 'receipt-test', 'ZR-RECEIPT-PG', CURRENT_DATE, 'READY', 95601)"), {"id": ids["request"]})
            c.execute(text("INSERT INTO supply_purchase_request_lines (id, tenant_id, purchase_request_id, product_id, quantity, unit_id, manual_future_quantity) VALUES (:id, 'receipt-test', :request, :product, 2, :unit, 2)"), {"id": ids["request_line"], "request": ids["request"], "product": ids["product"], "unit": ids["unit"]})
            c.execute(text("INSERT INTO supply_purchase_allocations (id, tenant_id, purchase_request_line_id, product_supplier_id, quantity_base, package_quantity_snapshot, package_unit_id_snapshot, packages_count, price_per_package_snapshot, base_unit_price_snapshot, currency, planned_amount, status) VALUES (:id, 'receipt-test', :line, :relation, 2, 1, :unit, 2, 50, 50, 'RUB', 100, 'CONFIRMED')"), {"id": ids["allocation"], "line": ids["request_line"], "relation": ids["relation"], "unit": ids["unit"]})
            c.execute(text("INSERT INTO supply_supplier_orders (id, tenant_id, number, supplier_id, purchase_request_id, status, total_amount, currency, created_by_user_id, confirmed_at, sent_at) VALUES (:id, 'receipt-test', 'PO-RECEIPT-PG', :supplier, :request, 'SENT', 100, 'RUB', 95601, now(), now())"), {"id": ids["order"], "supplier": ids["supplier"], "request": ids["request"]})
            c.execute(text("INSERT INTO supply_supplier_order_lines (id, tenant_id, supplier_order_id, source_allocation_id, product_id, product_name_snapshot, packages_count, package_quantity_snapshot, package_unit_id_snapshot, quantity_base, price_per_package_snapshot, base_unit_price_snapshot, planned_amount, currency, is_active_owner) VALUES (:id, 'receipt-test', :order, :allocation, :product, 'Receipt product', 2, 1, :unit, 2, 50, 50, 100, 'RUB', true)"), {"id": ids["order_line"], "order": ids["order"], "allocation": ids["allocation"], "product": ids["product"], "unit": ids["unit"]})
            c.execute(text("INSERT INTO supply_supplier_documents (id, tenant_id, supplier_order_id, supplier_id, document_type, document_number, document_date, status, supplier_display_name_snapshot, currency, total_amount, financial_role, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'receipt-test', :order, :supplier, 'UPD', 'UPD-RECEIPT-PG', CURRENT_DATE, 'RECORDED', 'МЕГАПРОД ООО', 'RUB', 100, 'SUPPORTING', 95601, now(), 95601)"), {"id": ids["document"], "order": ids["order"], "supplier": ids["supplier"]})
            c.execute(text("INSERT INTO supply_supplier_document_lines (id, tenant_id, supplier_document_id, supplier_order_id, supplier_order_line_id, product_name_snapshot, pricing_basis, package_quantity_snapshot, package_unit_id_snapshot, unit_name_snapshot, packages_count, quantity_base, price_per_package, line_amount, currency) VALUES (:id, 'receipt-test', :document, :order, :order_line, 'Receipt product', 'PACKAGE', 1, :unit, 'кг', 2, 2, 50, 100, 'RUB')"), {"id": ids["document_line"], "document": ids["document"], "order": ids["order"], "order_line": ids["order_line"], "unit": ids["unit"]})
            c.execute(text("INSERT INTO supply_supplier_acceptances (id, tenant_id, supplier_order_id, supplier_document_id, destination_mapping_id, status, received_at, recorded_by_user_id, recorded_at, created_by_user_id) VALUES (:id, 'receipt-test', :order, :document, :destination, 'RECORDED', now(), 95601, now(), 95601)"), {"id": ids["acceptance"], "order": ids["order"], "document": ids["document"], "destination": ids["destination"]})
            c.execute(text("INSERT INTO supply_supplier_acceptance_lines (id, tenant_id, acceptance_id, supplier_order_id, supplier_document_line_id, supplier_order_line_id, product_name_snapshot, product_id, unit_id, unit_name_snapshot, documented_quantity, received_quantity, accepted_quantity, rejected_quantity, documented_unit_price, accepted_unit_price, accepted_amount, currency) VALUES (:id, 'receipt-test', :acceptance, :order, :document_line, :order_line, 'Receipt product', :product, :unit, 'кг', 2, 2, 2, 0, 50, 50, 100, 'RUB')"), {"id": ids["acceptance_line"], "acceptance": ids["acceptance"], "order": ids["order"], "document_line": ids["document_line"], "order_line": ids["order_line"], "product": ids["product"], "unit": ids["unit"]})
            c.execute(text("INSERT INTO iiko_supplier_mappings (id, tenant_id, supplier_id, iiko_supplier_id, iiko_supplier_name, iiko_supplier_deleted, status, created_by_user_id) VALUES (:id, 'receipt-test', :supplier, :external, 'МЕГАПРОД ООО', false, 'CONFIRMED', 95601)"), {"id": ids["supplier_mapping"], "supplier": ids["supplier"], "external": ids["iiko_supplier"]})
            c.execute(text("INSERT INTO iiko_product_mappings (id, tenant_id, iiko_product_id, eos_product_id, status, source_name, source_unit_id, is_deleted, reasons) VALUES (:id, 'receipt-test', :external, :product, 'CONFIRMED', 'Receipt product', :unit_external, false, CAST('[]' AS JSONB))"), {"id": ids["product_mapping"], "external": ids["iiko_product"], "product": ids["product"], "unit_external": ids["iiko_unit"]})
            c.execute(text("INSERT INTO iiko_unit_mappings (id, tenant_id, iiko_unit_id, eos_unit_id, status, source_name, is_deleted, reasons) VALUES (:id, 'receipt-test', :external, :unit, 'CONFIRMED', 'кг', false, CAST('[]' AS JSONB))"), {"id": ids["unit_mapping"], "external": ids["iiko_unit"], "unit": ids["unit"]})
        return ids

    def test_cycle_constraints_immutability_and_concurrent_lifecycle(self):
        command.upgrade(self.config, "20260917_0055")
        command.upgrade(self.config, "20260917_0056")
        command.upgrade(self.config, "20260925_0057")
        command.downgrade(self.config, "20260917_0056")
        command.upgrade(self.config, "20260925_0057")
        self.assertEqual(self.revision(), "20260925_0057")
        ids = self.seed()
        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

        def prepare():
            with sessions() as session:
                return prepare_receipt(
                    session, ids["acceptance"], tenant_id="receipt-test", user_id=95601
                ).id

        with ThreadPoolExecutor(max_workers=2) as pool:
            prepared = [future.result(timeout=15) for future in (pool.submit(prepare), pool.submit(prepare))]
        self.assertEqual(len(set(prepared)), 1)
        receipt_id = prepared[0]
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(text("SELECT count(*) FROM supply_iiko_incoming_receipts")), 1)

        with sessions() as session:
            ready = mark_receipt_ready(session, receipt_id, tenant_id="receipt-test")
        self.assertEqual(ready.status.value, "READY")
        with self.assertRaises(DBAPIError), self.engine.begin() as c:
            c.execute(text("UPDATE supply_iiko_incoming_receipt_lines SET quantity=3 WHERE receipt_id=:id"), {"id": receipt_id})
        with self.engine.begin() as c:
            c.execute(text("UPDATE supply_iiko_incoming_receipt_lines SET accounted_quantity=0 WHERE receipt_id=:id"), {"id": receipt_id})

        provider = FakeProvider()
        def create():
            with sessions() as session:
                try:
                    return asyncio.run(create_receipt(session, provider, receipt_id, tenant_id="receipt-test")).status.value
                except IncomingReceiptStateError:
                    return "CONFLICT"
        with ThreadPoolExecutor(max_workers=2) as pool:
            create_results = [future.result(timeout=15) for future in (pool.submit(create), pool.submit(create))]
        self.assertEqual(provider.create_calls, 1)
        self.assertEqual(sorted(create_results), ["CONFLICT", "CREATED"])

        def process():
            with sessions() as session:
                try:
                    return asyncio.run(process_receipt(session, provider, receipt_id, tenant_id="receipt-test")).status.value
                except IncomingReceiptStateError:
                    return "CONFLICT"
        with ThreadPoolExecutor(max_workers=2) as pool:
            process_results = [future.result(timeout=15) for future in (pool.submit(process), pool.submit(process))]
        self.assertEqual(provider.process_calls, 1)
        self.assertEqual(provider.stock_calls, 1)
        self.assertEqual(sorted(process_results), ["CONFLICT", "POSTED"])
        with self.engine.connect() as c:
            accounted = c.execute(text("SELECT accounted_quantity, accounted_sum FROM supply_iiko_incoming_receipt_lines WHERE receipt_id=:id"), {"id": receipt_id}).one()
            self.assertEqual(accounted.accounted_quantity, Decimal("2.000000"))
            self.assertEqual(accounted.accounted_sum, Decimal("100.000000"))

        provider.fail_stock_refresh = True
        with sessions() as session:
            refreshed = asyncio.run(_finalize_posted(
                session,
                provider,
                receipt_id,
                tenant_id="receipt-test",
                invoice=provider.invoice(),
            ))
        self.assertEqual(refreshed.status.value, "POSTED")
        self.assertEqual(refreshed.last_error_code, "STOCK_REFRESH_FAILED")
        self.assertEqual(provider.stock_calls, 2)

        with self.assertRaises(IntegrityError) as invalid_status, self.engine.begin() as c:
            c.execute(text("UPDATE supply_iiko_incoming_receipts SET status='INVALID' WHERE id=:id"), {"id": receipt_id})
        self.assertEqual(invalid_status.exception.orig.sqlstate, "23514")


if __name__ == "__main__":
    unittest.main()
