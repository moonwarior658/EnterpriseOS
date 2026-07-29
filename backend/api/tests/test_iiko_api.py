import os
import unittest
from datetime import datetime

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_admin
from app.api.routes import iiko as iiko_routes
from app.core.config import settings
from app.db.session import get_db
from app.integrations.iiko.config import IikoSettings
from app.integrations.iiko.mapper import (
    map_product,
    map_stock_balance,
    map_unit,
    map_warehouse,
)
from app.integrations.iiko.provider import IikoProvider
from app.main import app
from app.models.iiko import IikoRawEntity, IikoSyncRun
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
        IikoSyncRun.__table__.create(self.engine)
        IikoRawEntity.__table__.create(self.engine)
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
                    ),
                    User(
                        id=2,
                        username="employee",
                        display_name="Сотрудник",
                        hashed_password="unused",
                        is_active=True,
                        is_admin=False,
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
