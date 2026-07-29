import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.mapper import (
    map_product,
    map_stock_balance,
    map_unit,
    map_warehouse,
)
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.service import (
    create_sync_run,
    stage_records,
    sync_reference_snapshot,
    sync_stock_balances,
    sync_warehouses,
)
from app.models.iiko import (
    IikoRawEntity,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
)
from app.models.user import User


class FakeProvider(IikoProvider):
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.product_name = "Молоко"
        self.stock_quantity = "1.500"

    async def authenticate(self) -> None:
        return None

    async def check_connection(self) -> bool:
        return True

    async def _read(self, name, records):
        if name in self.fail:
            raise IikoContractError(f"{name} unavailable")
        return records

    async def get_organizations(self):
        return await self._read("organizations", [])

    async def get_enterprises(self):
        return []

    async def get_departments(self):
        return []

    async def get_warehouses(self):
        return await self._read("warehouses", [])

    async def get_product_groups(self):
        return await self._read("product_groups", [])

    async def get_product_categories(self):
        return await self._read("product_categories", [])

    async def get_products(self):
        return await self._read(
            "products",
            [
                map_product(
                    {
                        "id": "product-1",
                        "name": self.product_name,
                        "mainUnit": "unit-1",
                        "deleted": False,
                    }
                )
            ],
        )

    async def get_units(self):
        return await self._read(
            "units",
            [
                map_unit(
                    {
                        "id": "unit-1",
                        "name": "Литр",
                        "code": "л",
                        "deleted": False,
                    }
                )
            ],
        )

    async def get_packages(self):
        return await self._read("packages", [])

    async def get_stock_balances(self, **kwargs):
        return [
            map_stock_balance(
                {
                    "store": kwargs["warehouse_external_ids"][0],
                    "product": "product-1",
                    "amount": self.stock_quantity,
                    "sum": 10,
                },
                calculated_at=datetime.combine(
                    kwargs["balance_date"],
                    datetime.min.time(),
                ),
            )
        ]

    async def aclose(self) -> None:
        return None


class IikoServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
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

    def tearDown(self) -> None:
        self.engine.dispose()

    async def sync(self, provider, tenant_id="tenant-a"):
        with self.session_factory() as session:
            return await sync_reference_snapshot(
                session,
                provider,
                tenant_id=tenant_id,
                requested_by=None,
                source_api_type="iiko_server",
            )

    async def test_success_and_idempotent_payload_hash(self) -> None:
        first = await self.sync(FakeProvider())
        second = await self.sync(FakeProvider())
        self.assertEqual(first.status, IikoSyncStatus.SUCCEEDED)
        self.assertEqual(first.records_created, 2)
        self.assertEqual(second.records_unchanged, 2)
        with self.session_factory() as session:
            self.assertEqual(
                session.scalar(select(func.count(IikoRawEntity.id))),
                2,
            )

    async def test_changed_payload_is_new_version_and_tenant_isolated(
        self,
    ) -> None:
        await self.sync(FakeProvider())
        changed = FakeProvider()
        changed.product_name = "Молоко 2"
        updated = await self.sync(changed)
        other = await self.sync(changed, tenant_id="tenant-b")
        self.assertEqual(updated.records_updated, 1)
        self.assertEqual(other.records_created, 2)
        with self.session_factory() as session:
            tenant_a = session.scalar(
                select(func.count(IikoRawEntity.id)).where(
                    IikoRawEntity.tenant_id == "tenant-a"
                )
            )
            tenant_b = session.scalar(
                select(func.count(IikoRawEntity.id)).where(
                    IikoRawEntity.tenant_id == "tenant-b"
                )
            )
        self.assertEqual(tenant_a, 3)
        self.assertEqual(tenant_b, 2)

    async def test_partial_and_total_failure_statuses(self) -> None:
        partial = await self.sync(FakeProvider(fail={"warehouses"}))
        self.assertEqual(partial.status, IikoSyncStatus.PARTIALLY_SUCCEEDED)
        self.assertEqual(partial.records_failed, 1)
        full = await self.sync(
            FakeProvider(
                fail={
                    "organizations",
                    "warehouses",
                    "product_groups",
                    "product_categories",
                    "products",
                    "units",
                    "packages",
                }
            ),
            tenant_id="tenant-full-failure",
        )
        self.assertEqual(full.status, IikoSyncStatus.FAILED)
        self.assertEqual(full.records_failed, 7)

    def test_transaction_error_rolls_back_staging_batch(self) -> None:
        with self.session_factory() as session:
            run = create_sync_run(
                session,
                tenant_id="tenant-a",
                sync_type=IikoSyncType.PRODUCTS,
                requested_by=None,
                source_api_type="iiko_server",
            )
            record = map_product(
                {
                    "id": "product-1",
                    "name": "Молоко",
                    "deleted": False,
                }
            )
            stage_records(session, run, [record])
            session.rollback()
        with self.session_factory() as session:
            self.assertEqual(
                session.scalar(select(func.count(IikoRawEntity.id))),
                0,
            )

    def test_secret_fields_are_removed_from_payload(self) -> None:
        with self.session_factory() as session:
            run = create_sync_run(
                session,
                tenant_id="tenant-a",
                sync_type=IikoSyncType.PRODUCTS,
                requested_by=None,
                source_api_type="iiko_server",
            )
            record = map_product(
                {
                    "id": "product-1",
                    "name": "Молоко",
                    "deleted": False,
                    "token": "must-not-be-stored",
                }
            )
            stage_records(session, run, [record])
            session.commit()
            payload = session.scalar(select(IikoRawEntity.payload))
        self.assertNotIn("token", payload)
        self.assertNotIn("must-not-be-stored", str(payload))

    async def test_stock_snapshot_identity_counters_and_parameters(
        self,
    ) -> None:
        async def sync_stock(provider):
            with self.session_factory() as session:
                return await sync_stock_balances(
                    session,
                    provider,
                    tenant_id="tenant-a",
                    requested_by=None,
                    source_api_type="iiko_server",
                    balance_date=date(2026, 7, 29),
                    warehouse_external_ids=["warehouse-1"],
                )

        first = await sync_stock(FakeProvider())
        second = await sync_stock(FakeProvider())
        changed_provider = FakeProvider()
        changed_provider.stock_quantity = "-2.250"
        changed = await sync_stock(changed_provider)
        self.assertEqual(first.records_created, 1)
        self.assertEqual(second.records_unchanged, 1)
        self.assertEqual(changed.records_updated, 1)
        self.assertEqual(first.parameters["balance_date"], "2026-07-29")
        self.assertEqual(
            first.parameters["warehouse_external_ids"],
            ["warehouse-1"],
        )

    async def test_warehouse_sync_success_and_failure_counters(self) -> None:
        class WarehouseProvider(FakeProvider):
            async def get_warehouses(self):
                return await self._read(
                    "warehouses",
                    [
                        map_warehouse(
                            {
                                "id": "warehouse-1",
                                "name": "Основной склад",
                                "type": "INVENTORY_ASSETS",
                                "deleted": False,
                            }
                        )
                    ],
                )

        with self.session_factory() as session:
            succeeded = await sync_warehouses(
                session,
                WarehouseProvider(),
                tenant_id="tenant-a",
                requested_by=None,
                source_api_type="iiko_server",
            )
        self.assertEqual(succeeded.status, IikoSyncStatus.SUCCEEDED)
        self.assertEqual(succeeded.records_created, 1)
        self.assertEqual(succeeded.records_failed, 0)

        with self.session_factory() as session:
            with self.assertRaises(IikoContractError):
                await sync_warehouses(
                    session,
                    WarehouseProvider(fail={"warehouses"}),
                    tenant_id="tenant-failed",
                    requested_by=None,
                    source_api_type="iiko_server",
                )
            failed = session.scalar(
                select(IikoSyncRun).where(
                    IikoSyncRun.tenant_id == "tenant-failed"
                )
            )
        self.assertEqual(failed.status, IikoSyncStatus.FAILED)
        self.assertEqual(failed.records_failed, 1)
