import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_admin
from app.api.routes import iiko as iiko_routes
from app.core.config import settings
from app.db.session import get_db
from app.integrations.iiko.config import IikoSettings
from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.mapper import (
    map_product,
    map_stock_balance,
    map_unit,
    map_warehouse,
)
from app.integrations.iiko.schemas import (
    IikoAccountDto,
    IikoIncomingInvoiceDto,
    IikoOutgoingInvoiceDto,
)
from app.integrations.iiko.provider import IikoProvider
from app.main import app
from app.models.iiko import (
    IikoMappingStatus,
    IikoRawEntity,
    IikoStockBalanceSnapshotLine,
    IikoStockBalanceSnapshotSource,
    IikoSyncRun,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import Department, LegalContour
from app.models.user import User


class ApiProvider(IikoProvider):
    async def authenticate(self) -> None:
        return None

    async def check_connection(self) -> bool:
        return True

    async def get_organizations(self):
        return []

    async def get_enterprises(self):
        return []

    async def get_departments(self):
        return []

    async def get_warehouses(self):
        return [
            map_warehouse(
                {
                    "id": "warehouse-1",
                    "name": "Основной склад",
                    "type": "INVENTORY_ASSETS",
                    "deleted": False,
                }
            )
        ]

    async def get_product_groups(self):
        return []

    async def get_product_categories(self):
        return []

    async def get_products(self):
        return [
            map_product(
                {
                    "id": f"product-{number}",
                    "name": f"Товар {number}",
                    "deleted": False,
                }
            )
            for number in range(3)
        ]

    async def get_units(self):
        return [
            map_unit(
                {
                    "id": "unit-1",
                    "name": "Штука",
                    "code": "шт",
                    "deleted": False,
                }
            )
        ]

    async def get_packages(self):
        return []

    async def get_stock_balances(self, **kwargs):
        return [
            map_stock_balance(
                {
                    "store": kwargs["warehouse_external_ids"][0],
                    "product": "product-1",
                    "amount": "-1.250",
                    "sum": -10,
                },
                calculated_at=datetime.combine(
                    kwargs["balance_date"],
                    datetime.min.time(),
                ),
            ),
            map_stock_balance(
                {
                    "store": kwargs["warehouse_external_ids"][0],
                    "product": "product-2",
                    "amount": "0",
                    "sum": 0,
                },
                calculated_at=datetime.combine(
                    kwargs["balance_date"],
                    datetime.min.time(),
                ),
            ),
        ]

    async def get_accounts(self):
        if error := getattr(self, "accounts_error", None):
            raise error
        return list(getattr(self, "accounts", [
            IikoAccountDto(
                external_id=str(uuid4()),
                name="Задолженность покупателей",
                code="7.3",
                account_type="ACCOUNTS_RECEIVABLE",
            ),
            IikoAccountDto(
                external_id=str(uuid4()),
                name="Выручка",
                code="4.01.1",
                account_type="INCOME",
            ),
        ]))

    async def get_outgoing_invoices(self, *, date_from, date_to):
        if error := getattr(self, "outgoing_invoices_error", None):
            raise error
        self.outgoing_invoice_period = (date_from, date_to)
        return list(getattr(self, "outgoing_invoices", []))

    async def get_incoming_invoices(self, *, date_from, date_to):
        self.incoming_invoice_period = (date_from, date_to)
        return list(getattr(self, "incoming_invoices", []))

    async def get_suppliers(self):
        if error := getattr(self, "suppliers_error", None):
            raise error
        return list(getattr(self, "suppliers", []))

    async def aclose(self) -> None:
        return None


class IikoApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        User.__table__.create(self.engine)
        Department.__table__.create(self.engine)
        IikoSyncRun.__table__.create(self.engine)
        IikoRawEntity.__table__.create(self.engine)
        IikoWarehouseMapping.__table__.create(self.engine)
        IikoStockBalanceSnapshotSource.__table__.create(self.engine)
        IikoStockBalanceSnapshotLine.__table__.create(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        with self.session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        id=1,
                        username="admin",
                        display_name="Администратор",
                        hashed_password="unused",
                        is_active=True,
                        is_admin=True,
                        tenant_id="tenant-a",
                    ),
                    User(
                        id=2,
                        username="employee",
                        display_name="Сотрудник",
                        hashed_password="unused",
                        is_active=True,
                        is_admin=False,
                        tenant_id="tenant-a",
                    ),
                ]
            )

        def override_db():
            with self.session_factory() as session:
                yield session

        def override_admin():
            with self.session_factory() as session:
                return session.get(User, 1)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_admin] = override_admin
        app.dependency_overrides[
            iiko_routes.get_iiko_provider
        ] = lambda: ApiProvider()
        self.config = IikoSettings(
            enabled=True,
            base_url="https://iiko.example.test/resto",
            login="user",
            password="password",
        )
        self.original_get_config = iiko_routes.get_iiko_settings
        iiko_routes.get_iiko_settings = lambda: self.config
        self.previous_tenant_id = settings.default_tenant_id
        settings.default_tenant_id = "tenant-a"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        iiko_routes.get_iiko_settings = self.original_get_config
        settings.default_tenant_id = self.previous_tenant_id
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine.dispose()

    def test_admin_status_has_no_credentials(self) -> None:
        response = self.client.get("/integrations/iiko/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["enabled"])
        self.assertTrue(body["configured"])
        rendered = str(body)
        self.assertNotIn("password", rendered)
        self.assertNotIn("user", rendered)
        self.assertNotIn("base_url", rendered)

    def test_products_are_paginated_and_searchable(self) -> None:
        response = self.client.get(
            "/integrations/iiko/products",
            params={"limit": 1, "offset": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 3)
        self.assertEqual(len(response.json()["items"]), 1)
        searched = self.client.get(
            "/integrations/iiko/products",
            params={"search": "Товар 2"},
        )
        self.assertEqual(searched.json()["total"], 1)

    def test_test_connection_records_success(self) -> None:
        response = self.client.post("/integrations/iiko/test-connection")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        runs = self.client.get("/integrations/iiko/sync-runs")
        self.assertEqual(len(runs.json()), 1)
        detail = self.client.get(
            f"/integrations/iiko/sync-runs/{response.json()['id']}"
        )
        self.assertEqual(detail.status_code, 200)

    def test_disabled_integration_is_safe_conflict(self) -> None:
        self.config.enabled = False
        response = self.client.post("/integrations/iiko/test-connection")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "IIKO_DISABLED")
        status_response = self.client.get("/integrations/iiko/status")
        self.assertEqual(
            status_response.json()["connection_state"],
            "disabled",
        )

    def test_invalid_configuration_is_safe_conflict(self) -> None:
        self.config = IikoSettings(enabled=True)
        response = self.client.post("/integrations/iiko/test-connection")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "IIKO_NOT_CONFIGURED")

    def test_non_admin_is_forbidden(self) -> None:
        def forbidden():
            raise HTTPException(status_code=403, detail="forbidden")

        app.dependency_overrides[get_current_admin] = forbidden
        response = self.client.get("/integrations/iiko/status")
        self.assertEqual(response.status_code, 403)

    def test_pagination_limit_is_bounded(self) -> None:
        response = self.client.get(
            "/integrations/iiko/products",
            params={"limit": 501},
        )
        self.assertEqual(response.status_code, 422)

    def test_stock_balances_require_warehouse_and_date(self) -> None:
        missing = self.client.get("/integrations/iiko/stock-balances")
        self.assertEqual(missing.status_code, 422)
        response = self.client.get(
            "/integrations/iiko/stock-balances",
            params={
                "warehouse_external_id": "warehouse-1",
                "balance_date": "2026-07-29",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(response.json()["items"][0]["quantity"], "-1.250")
        paged = self.client.get(
            "/integrations/iiko/stock-balances",
            params={
                "warehouse_external_id": "warehouse-1",
                "balance_date": "2026-07-29",
                "limit": 1,
                "offset": 1,
            },
        )
        self.assertEqual(paged.json()["total"], 2)
        self.assertEqual(len(paged.json()["items"]), 1)
        invalid_date = self.client.get(
            "/integrations/iiko/stock-balances",
            params={
                "warehouse_external_id": "warehouse-1",
                "balance_date": "not-a-date",
            },
        )
        self.assertEqual(invalid_date.status_code, 422)

    def test_outgoing_invoice_contract_discovery_is_read_only_and_explicit(
        self,
    ) -> None:
        department_id = uuid4()
        destination_mapping_id = uuid4()
        destination_warehouse_id = uuid4()
        destination_counteragent_id = uuid4()
        household_mapping_id = uuid4()
        household_warehouse_id = uuid4()
        household_counteragent_id = uuid4()
        with self.session_factory.begin() as session:
            session.add(Department(
                id=department_id,
                tenant_id="tenant-a",
                code="M15",
                name="М15",
                legal_contour=LegalContour.IP,
            ))
            session.add(IikoWarehouseMapping(
                id=destination_mapping_id,
                tenant_id="tenant-a",
                iiko_warehouse_id=destination_warehouse_id,
                eos_department_id=department_id,
                destination_type=IikoWarehouseDestinationType.DESTINATION,
                role=IikoWarehouseRole.MAIN,
                status=IikoMappingStatus.CONFIRMED,
                source_name="М15 Основной",
            ))
            session.add(IikoWarehouseMapping(
                id=household_mapping_id,
                tenant_id="tenant-a",
                iiko_warehouse_id=household_warehouse_id,
                eos_department_id=department_id,
                destination_type=IikoWarehouseDestinationType.DESTINATION,
                role=IikoWarehouseRole.HOUSEHOLD,
                status=IikoMappingStatus.CONFIRMED,
                source_name="М15 Хозяйственный",
            ))

        provider = ApiProvider()
        provider.accounts = [
            IikoAccountDto(
                external_id=str(destination_warehouse_id),
                name="М15 Основной",
                code="10.1",
                account_type="INVENTORY_ASSETS",
            ),
            IikoAccountDto(
                external_id=str(uuid4()),
                name="Задолженность покупателей",
                code="21",
                account_type="ACCOUNTS_RECEIVABLE",
            ),
            IikoAccountDto(
                external_id=str(uuid4()),
                name="Выручка",
                code="20",
                account_type="INCOME",
            ),
        ]
        incoming_main_id = uuid4()
        incoming_packaging_id = uuid4()
        incoming_household_id = uuid4()
        main_source_id = uuid4()
        packaging_source_id = uuid4()
        household_source_id = uuid4()
        provider.incoming_invoices = [
            IikoIncomingInvoiceDto(
                external_id=str(incoming_main_id),
                document_number="ПН-2686-MAIN",
                status="PROCESSED",
                default_store_id=str(destination_warehouse_id),
            ),
            IikoIncomingInvoiceDto(
                external_id=str(incoming_packaging_id),
                document_number="ПН-2686-PACKAGING",
                status="PROCESSED",
                default_store_id=str(destination_warehouse_id),
            ),
            IikoIncomingInvoiceDto(
                external_id=str(incoming_household_id),
                document_number="ПН-2686-HOUSEHOLD",
                status="PROCESSED",
                default_store_id=str(household_warehouse_id),
            ),
        ]
        provider.outgoing_invoices = [
            IikoOutgoingInvoiceDto(
                document_number="2686-MAIN",
                status="PROCESSED",
                linked_incoming_invoice_id=str(incoming_main_id),
                counteragent_id=str(destination_counteragent_id),
                default_store_id=str(main_source_id),
                account_to_code="21",
                revenue_account_code="20",
            ),
            IikoOutgoingInvoiceDto(
                document_number="2686-PACKAGING",
                status="PROCESSED",
                linked_incoming_invoice_id=str(incoming_packaging_id),
                counteragent_id=str(destination_counteragent_id),
                default_store_id=str(packaging_source_id),
                account_to_code="21",
                revenue_account_code="20",
            ),
            IikoOutgoingInvoiceDto(
                document_number="2686-HOUSEHOLD",
                status="PROCESSED",
                linked_incoming_invoice_id=str(incoming_household_id),
                counteragent_id=str(household_counteragent_id),
                default_store_id=str(household_source_id),
                account_to_code="21",
                revenue_account_code="20",
            ),
        ]
        app.dependency_overrides[
            iiko_routes.get_iiko_provider
        ] = lambda: provider
        response = self.client.get(
            "/integrations/iiko/outgoing-invoice-contracts",
            params={
                "department_id": str(department_id),
                "date_from": "2026-01-01",
                "date_to": "2026-08-10",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["incoming_invoices_read"], 3)
        self.assertEqual(body["invoices_read"], 3)
        destinations = {
            item["destination_role"]: item for item in body["destinations"]
        }
        main = destinations["MAIN"]
        household = destinations["HOUSEHOLD"]
        self.assertEqual(main["status"], "UNIQUE")
        self.assertEqual(
            main["destination_counteragent_id"],
            str(destination_counteragent_id),
        )
        candidate = main["candidates"][0]
        self.assertEqual(
            candidate["counteragent_id"], str(destination_counteragent_id)
        )
        self.assertEqual(candidate["account_to_code"], "21")
        self.assertEqual(candidate["revenue_account_code"], "20")
        self.assertEqual(
            candidate["document_numbers"],
            ["2686-MAIN", "2686-PACKAGING"],
        )
        self.assertEqual(
            set(candidate["source_warehouse_ids"]),
            {str(main_source_id), str(packaging_source_id)},
        )
        self.assertEqual(household["status"], "UNIQUE")
        self.assertEqual(
            household["destination_counteragent_id"],
            str(household_counteragent_id),
        )
        self.assertEqual(
            household["candidates"][0]["source_warehouse_ids"],
            [str(household_source_id)],
        )

        provider.outgoing_invoices.append(IikoOutgoingInvoiceDto(
            external_id=str(uuid4()),
            document_number="РН-101",
            date_incoming=datetime(2026, 8, 2, tzinfo=timezone.utc),
            status="NEW",
            linked_incoming_invoice_id=str(incoming_main_id),
            counteragent_id=str(destination_counteragent_id),
            default_store_id=str(uuid4()),
            account_to_code="7.4",
            revenue_account_code="4.02",
        ))
        conflict = self.client.get(
            "/integrations/iiko/outgoing-invoice-contracts",
            params={
                "department_id": str(department_id),
                "date_from": "2026-01-01",
                "date_to": "2026-08-10",
            },
        )
        self.assertEqual(
            next(
                item for item in conflict.json()["destinations"]
                if item["destination_role"] == "MAIN"
            )["status"],
            "CONFLICT",
        )

        provider.accounts_error = IikoContractError(
            "accounts malformed password=must-not-leak"
        )
        with self.assertLogs(
            "app.integrations.iiko.contract_discovery",
            level="ERROR",
        ) as captured:
            accounts_error = self.client.get(
                "/integrations/iiko/outgoing-invoice-contracts",
                params={
                    "department_id": str(department_id),
                    "date_from": "2026-01-01",
                    "date_to": "2026-08-10",
                },
            )
        self.assertEqual(accounts_error.status_code, 502)
        self.assertEqual(accounts_error.json()["detail"], "IIKO_CONTRACT_ERROR")
        rendered = "\n".join(captured.output)
        self.assertIn("stage=accounts", rendered)
        self.assertIn("accounts malformed", rendered)
        self.assertNotIn("must-not-leak", rendered)
        del provider.accounts_error

        provider.outgoing_invoices_error = IikoContractError(
            "Missing outgoing invoice field "
            "document_number=РН-500 field=accountToCode"
        )
        with self.assertLogs(
            "app.integrations.iiko.contract_discovery",
            level="ERROR",
        ) as captured:
            invoice_error = self.client.get(
                "/integrations/iiko/outgoing-invoice-contracts",
                params={
                    "department_id": str(department_id),
                    "date_from": "2026-01-01",
                    "date_to": "2026-08-10",
                },
            )
        self.assertEqual(invoice_error.status_code, 502)
        self.assertEqual(invoice_error.json()["detail"], "IIKO_CONTRACT_ERROR")
        rendered = "\n".join(captured.output)
        self.assertIn("stage=outgoingInvoice", rendered)
        self.assertIn("document_number=РН-500", rendered)
        self.assertIn("field=accountToCode", rendered)
        del provider.outgoing_invoices_error

        provider.accounts[0] = provider.accounts[0].model_copy(
            update={"organization_external_id": "invalid-uuid"}
        )
        parent_ignored = self.client.get(
            "/integrations/iiko/outgoing-invoice-contracts",
            params={
                "department_id": str(department_id),
                "date_from": "2026-01-01",
                "date_to": "2026-08-10",
            },
        )
        self.assertEqual(parent_ignored.status_code, 200)
        parent_ignored_main = next(
            item for item in parent_ignored.json()["destinations"]
            if item["destination_role"] == "MAIN"
        )
        self.assertEqual(
            parent_ignored_main["destination_counteragent_id"],
            str(destination_counteragent_id),
        )

        today = date.today()
        clamped_period = self.client.get(
            "/integrations/iiko/outgoing-invoice-contracts",
            params={
                "department_id": str(department_id),
                "date_from": (today - timedelta(days=500)).isoformat(),
                "date_to": today.isoformat(),
            },
        )
        self.assertEqual(clamped_period.status_code, 200)
        expected_from = today - timedelta(days=45)
        self.assertEqual(
            provider.outgoing_invoice_period,
            (expected_from, today),
        )
        self.assertEqual(
            clamped_period.json()["date_from"],
            expected_from.isoformat(),
        )

    def test_warehouse_and_stock_sync_are_admin_only_and_record_scope(
        self,
    ) -> None:
        warehouse = self.client.post("/integrations/iiko/sync/warehouses")
        self.assertEqual(warehouse.status_code, 200)
        self.assertEqual(warehouse.json()["records_created"], 1)
        stock = self.client.post(
            "/integrations/iiko/sync/stock-balances",
            json={
                "balance_date": "2026-07-29",
                "warehouse_external_ids": ["warehouse-1"],
            },
        )
        self.assertEqual(stock.status_code, 200)
        self.assertEqual(
            stock.json()["parameters"]["balance_date"],
            "2026-07-29",
        )
        self.assertEqual(stock.json()["records_created"], 2)

    def test_manual_stock_balance_snapshot_endpoint(self) -> None:
        department_id = uuid4()
        source_id = uuid4()
        warehouse_id = uuid4()
        product_id = uuid4()
        unit_id = uuid4()
        with self.session_factory.begin() as session:
            session.add(Department(
                id=department_id,
                tenant_id="tenant-a",
                code="M15",
                name="М15",
                legal_contour=LegalContour.IP,
            ))
            session.add(IikoWarehouseMapping(
                id=source_id,
                tenant_id="tenant-a",
                iiko_warehouse_id=warehouse_id,
                destination_type=IikoWarehouseDestinationType.SOURCE,
                role=IikoWarehouseRole.MAIN,
                legal_contour=LegalContour.IP,
                status=IikoMappingStatus.CONFIRMED,
                source_name="Источник",
            ))
            foreign_department_id = uuid4()
            foreign_source_id = uuid4()
            session.add(Department(
                id=foreign_department_id,
                tenant_id="tenant-b",
                code="FOREIGN",
                name="Чужое подразделение",
                legal_contour=LegalContour.IP,
            ))
            session.add(IikoWarehouseMapping(
                id=foreign_source_id,
                tenant_id="tenant-b",
                iiko_warehouse_id=uuid4(),
                destination_type=IikoWarehouseDestinationType.SOURCE,
                role=IikoWarehouseRole.MAIN,
                legal_contour=LegalContour.IP,
                status=IikoMappingStatus.CONFIRMED,
                source_name="Чужой SOURCE",
            ))

        class SnapshotApiProvider(ApiProvider):
            async def get_stock_balances(self, **kwargs):
                return [map_stock_balance(
                    {
                        "store": str(warehouse_id),
                        "product": str(product_id),
                        "amount": "4.250",
                    },
                    calculated_at=kwargs["snapshot_at"],
                    product=type("Product", (), {
                        "base_unit_external_id": str(unit_id),
                        "name": "Товар",
                    })(),
                )]

        app.dependency_overrides[
            iiko_routes.get_iiko_provider
        ] = lambda: SnapshotApiProvider()
        snapshot_at = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)
        for rejected_department_id, rejected_source_id in (
            (foreign_department_id, foreign_source_id),
            (department_id, foreign_source_id),
            (foreign_department_id, source_id),
        ):
            foreign = self.client.post(
                "/integrations/iiko/sync/stock-balance-snapshot",
                json={
                    "snapshot_at": snapshot_at.isoformat(),
                    "department_id": str(rejected_department_id),
                    "source_warehouse_mapping_ids": [
                        str(rejected_source_id)
                    ],
                },
            )
            self.assertEqual(foreign.status_code, 422, foreign.text)
        duplicate = self.client.post(
            "/integrations/iiko/sync/stock-balance-snapshot",
            json={
                "snapshot_at": snapshot_at.isoformat(),
                "department_id": str(department_id),
                "source_warehouse_mapping_ids": [str(source_id), str(source_id)],
            },
        )
        self.assertEqual(duplicate.status_code, 422, duplicate.text)
        response = self.client.post(
            "/integrations/iiko/sync/stock-balance-snapshot",
            json={
                "snapshot_at": snapshot_at.isoformat(),
                "department_id": str(department_id),
                "source_warehouse_mapping_ids": [str(source_id)],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sync_type"], "STOCK_BALANCE_SNAPSHOT")
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        with self.session_factory() as session:
            line = session.scalar(select(IikoStockBalanceSnapshotLine))
        self.assertEqual(line.source_warehouse_mapping_id, source_id)
        self.assertEqual(line.quantity, Decimal("4.250000"))
