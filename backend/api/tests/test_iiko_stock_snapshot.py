import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.mapper import map_stock_balance
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.service import sync_stock_balance_snapshot
from app.models.iiko import (
    IikoMappingStatus,
    IikoStockBalanceSnapshotLine,
    IikoStockBalanceSnapshotSource,
    IikoStockBalanceSnapshotSourceStatus,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import Department, LegalContour
from app.models.user import User
from app.supply.iiko_stock import _latest_balances


class SnapshotProvider(IikoProvider):
    def __init__(self) -> None:
        self.quantities: dict[UUID, Decimal] = {}
        self.fail_warehouses: set[UUID] = set()
        self.empty_warehouses: set[UUID] = set()
        self.calls: list[tuple[datetime, UUID]] = []
        self.product_id = uuid4()
        self.unit_id = uuid4()

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
        return []

    async def get_product_groups(self):
        return []

    async def get_product_categories(self):
        return []

    async def get_products(self):
        return []

    async def get_units(self):
        return []

    async def get_packages(self):
        return []

    async def get_stock_balances(self, **kwargs):
        snapshot_at = kwargs["snapshot_at"]
        warehouse_id = UUID(kwargs["warehouse_external_ids"][0])
        self.calls.append((snapshot_at, warehouse_id))
        if warehouse_id in self.fail_warehouses:
            raise IikoContractError("warehouse unavailable")
        if warehouse_id in self.empty_warehouses:
            return []
        return [map_stock_balance(
            {
                "store": str(warehouse_id),
                "product": str(self.product_id),
                "amount": str(self.quantities.get(warehouse_id, Decimal("0"))),
            },
            calculated_at=snapshot_at,
            product=type("Product", (), {
                "base_unit_external_id": str(self.unit_id),
                "name": "Товар",
            })(),
        )]

    async def aclose(self) -> None:
        return None


class IikoStockSnapshotTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        User.__table__.create(self.engine)
        Department.__table__.create(self.engine)
        IikoSyncRun.__table__.create(self.engine)
        IikoWarehouseMapping.__table__.create(self.engine)
        IikoStockBalanceSnapshotSource.__table__.create(self.engine)
        IikoStockBalanceSnapshotLine.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.department_id = uuid4()
        self.source_ids = [uuid4(), uuid4()]
        self.warehouse_ids = [uuid4(), uuid4()]
        with self.sessions.begin() as session:
            session.add(Department(
                id=self.department_id,
                tenant_id="tenant-a",
                code="dept-a",
                name="Подразделение",
                legal_contour=LegalContour.IP,
                is_active=True,
            ))
            for source_id, warehouse_id in zip(
                self.source_ids, self.warehouse_ids, strict=True
            ):
                session.add(IikoWarehouseMapping(
                    id=source_id,
                    tenant_id="tenant-a",
                    iiko_warehouse_id=warehouse_id,
                    destination_type=IikoWarehouseDestinationType.SOURCE,
                    role=IikoWarehouseRole.MAIN,
                    legal_contour=LegalContour.IP,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name=f"SOURCE {source_id}",
                    is_deleted=False,
                ))
        self.snapshot_at = datetime(2026, 8, 5, 9, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.engine.dispose()

    async def _sync(self, provider, source_ids=None, snapshot_at=None):
        with self.sessions() as session:
            return await sync_stock_balance_snapshot(
                session,
                provider,
                tenant_id="tenant-a",
                requested_by=None,
                source_api_type="iiko_server",
                snapshot_at=snapshot_at or self.snapshot_at,
                department_id=self.department_id,
                source_warehouse_mapping_ids=source_ids or [self.source_ids[0]],
            )

    async def test_successful_snapshot_for_one_source(self) -> None:
        provider = SnapshotProvider()
        provider.quantities[self.warehouse_ids[0]] = Decimal("12.500")
        run = await self._sync(provider)
        self.assertEqual(run.sync_type, IikoSyncType.STOCK_BALANCE_SNAPSHOT)
        self.assertEqual(run.status, IikoSyncStatus.SUCCEEDED)
        self.assertEqual(provider.calls, [(self.snapshot_at, self.warehouse_ids[0])])
        self.assertIsNotNone(provider.calls[0][0].utcoffset())
        self.assertEqual(run.parameters["snapshot_at"], self.snapshot_at.isoformat())
        with self.sessions() as session:
            line = session.scalar(select(IikoStockBalanceSnapshotLine))
            source = session.scalar(select(IikoStockBalanceSnapshotSource))
        self.assertEqual(line.tenant_id, "tenant-a")
        self.assertEqual(line.department_id, self.department_id)
        self.assertEqual(line.source_warehouse_mapping_id, self.source_ids[0])
        self.assertEqual(line.iiko_warehouse_id, self.warehouse_ids[0])
        self.assertEqual(line.iiko_product_id, provider.product_id)
        self.assertEqual(line.iiko_unit_id, provider.unit_id)
        self.assertEqual(line.quantity, Decimal("12.500000"))
        self.assertEqual(self._as_utc(line.snapshot_at), self.snapshot_at)
        self.assertEqual(self._as_utc(source.snapshot_at), self.snapshot_at)

    async def test_snapshot_for_multiple_sources(self) -> None:
        provider = SnapshotProvider()
        run = await self._sync(provider, self.source_ids)
        self.assertEqual(run.status, IikoSyncStatus.SUCCEEDED)
        self.assertEqual(run.records_created, 2)
        self.assertEqual(
            {warehouse for _, warehouse in provider.calls},
            set(self.warehouse_ids),
        )

    async def test_partial_source_error_is_not_succeeded(self) -> None:
        provider = SnapshotProvider()
        provider.fail_warehouses.add(self.warehouse_ids[1])
        commit_count = 0
        with self.sessions() as session:
            @event.listens_for(session, "after_commit")
            def count_commit(_session) -> None:
                nonlocal commit_count
                commit_count += 1

            run = await sync_stock_balance_snapshot(
                session,
                provider,
                tenant_id="tenant-a",
                requested_by=None,
                source_api_type="iiko_server",
                snapshot_at=self.snapshot_at,
                department_id=self.department_id,
                source_warehouse_mapping_ids=self.source_ids,
            )
        self.assertEqual(run.status, IikoSyncStatus.PARTIALLY_SUCCEEDED)
        self.assertNotEqual(run.status, IikoSyncStatus.SUCCEEDED)
        self.assertEqual(run.records_created, 1)
        self.assertEqual(run.records_failed, 1)
        self.assertEqual(commit_count, 1)
        with self.sessions() as session:
            sources = list(session.scalars(
                select(IikoStockBalanceSnapshotSource).order_by(
                    IikoStockBalanceSnapshotSource.source_warehouse_mapping_id
                )
            ))
        self.assertEqual(
            {source.status for source in sources},
            {
                IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
                IikoStockBalanceSnapshotSourceStatus.FAILED,
            },
        )

    async def test_new_snapshot_does_not_change_old_snapshot(self) -> None:
        provider = SnapshotProvider()
        provider.quantities[self.warehouse_ids[0]] = Decimal("1")
        first = await self._sync(provider)
        provider.quantities[self.warehouse_ids[0]] = Decimal("9")
        second = await self._sync(
            provider,
            snapshot_at=self.snapshot_at + timedelta(hours=1),
        )
        with self.sessions() as session:
            lines = list(session.scalars(
                select(IikoStockBalanceSnapshotLine).order_by(
                    IikoStockBalanceSnapshotLine.snapshot_at
                )
            ))
        self.assertNotEqual(first.id, second.id)
        self.assertEqual([line.quantity for line in lines], [Decimal("1"), Decimal("9")])
        self.assertEqual([line.sync_run_id for line in lines], [first.id, second.id])

    async def test_calculation_reads_only_latest_succeeded_snapshot(self) -> None:
        provider = SnapshotProvider()
        provider.quantities[self.warehouse_ids[0]] = Decimal("2")
        await self._sync(provider)
        provider.quantities[self.warehouse_ids[0]] = Decimal("7")
        latest_at = self.snapshot_at + timedelta(hours=1)
        await self._sync(provider, snapshot_at=latest_at)
        provider.quantities[self.warehouse_ids[0]] = Decimal("99")
        provider.fail_warehouses.add(self.warehouse_ids[1])
        partial_at = self.snapshot_at + timedelta(hours=2)
        await self._sync(provider, self.source_ids, partial_at)
        with self.sessions.begin() as session:
            reference_run = IikoSyncRun(
                tenant_id="tenant-a",
                sync_type=IikoSyncType.FULL_REFERENCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
                finished_at=partial_at + timedelta(hours=1),
                parameters={
                    "snapshot_at": (partial_at + timedelta(hours=1)).isoformat(),
                    "completed_source_warehouse_mapping_ids": [
                        str(self.source_ids[0])
                    ],
                },
            )
            session.add(reference_run)
            session.flush()
            session.add(IikoStockBalanceSnapshotSource(
                tenant_id="tenant-a",
                sync_run_id=reference_run.id,
                department_id=self.department_id,
                source_warehouse_mapping_id=self.source_ids[0],
                snapshot_at=partial_at + timedelta(hours=1),
                status=IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
            ))
            session.flush()
            session.add(IikoStockBalanceSnapshotLine(
                tenant_id="tenant-a",
                sync_run_id=reference_run.id,
                department_id=self.department_id,
                source_warehouse_mapping_id=self.source_ids[0],
                iiko_warehouse_id=self.warehouse_ids[0],
                iiko_product_id=provider.product_id,
                iiko_unit_id=provider.unit_id,
                quantity=Decimal("500"),
                snapshot_at=partial_at + timedelta(hours=1),
            ))
        with self.sessions() as session:
            balances, selected_at = _latest_balances(
                session,
                tenant_id="tenant-a",
                source_warehouse_mapping_id=self.source_ids[0],
            )
        self.assertEqual(balances, {provider.product_id: Decimal("7")})
        self.assertEqual(self._as_utc(selected_at), latest_at)

    async def test_empty_successful_source_is_recorded(self) -> None:
        provider = SnapshotProvider()
        provider.empty_warehouses.add(self.warehouse_ids[0])
        run = await self._sync(provider)
        self.assertEqual(run.status, IikoSyncStatus.SUCCEEDED)
        with self.sessions() as session:
            source = session.scalar(select(IikoStockBalanceSnapshotSource))
            line_count = session.scalar(
                select(func.count()).select_from(IikoStockBalanceSnapshotLine)
            )
        self.assertEqual(
            source.status, IikoStockBalanceSnapshotSourceStatus.SUCCEEDED
        )
        self.assertEqual(line_count, 0)

    async def test_negative_and_six_decimal_quantities_are_preserved(self) -> None:
        provider = SnapshotProvider()
        provider.quantities[self.warehouse_ids[0]] = Decimal("-1.123456")
        run = await self._sync(provider)
        self.assertEqual(run.status, IikoSyncStatus.SUCCEEDED)
        with self.sessions() as session:
            line = session.scalar(select(IikoStockBalanceSnapshotLine))
        self.assertEqual(line.quantity, Decimal("-1.123456"))

    async def test_more_than_six_decimal_places_fail_source(self) -> None:
        provider = SnapshotProvider()
        provider.quantities[self.warehouse_ids[0]] = Decimal("1.1234567")
        run = await self._sync(provider)
        self.assertEqual(run.status, IikoSyncStatus.FAILED)
        with self.sessions() as session:
            source = session.scalar(select(IikoStockBalanceSnapshotSource))
            line_count = session.scalar(
                select(func.count()).select_from(IikoStockBalanceSnapshotLine)
            )
        self.assertEqual(source.status, IikoStockBalanceSnapshotSourceStatus.FAILED)
        self.assertEqual(line_count, 0)

    async def test_database_error_rolls_back_entire_snapshot(self) -> None:
        provider = SnapshotProvider()

        def fail_snapshot_line_insert(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ) -> None:
            if "INSERT INTO iiko_stock_balance_snapshot_lines" in statement:
                raise RuntimeError("injected snapshot write failure")

        event.listen(self.engine, "before_cursor_execute", fail_snapshot_line_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "injected snapshot"):
                await self._sync(provider)
        finally:
            event.remove(
                self.engine, "before_cursor_execute", fail_snapshot_line_insert
            )
        with self.sessions() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(IikoSyncRun)
            ), 0)
            self.assertEqual(session.scalar(
                select(func.count()).select_from(IikoStockBalanceSnapshotSource)
            ), 0)
            self.assertEqual(session.scalar(
                select(func.count()).select_from(IikoStockBalanceSnapshotLine)
            ), 0)


if __name__ == "__main__":
    unittest.main()
