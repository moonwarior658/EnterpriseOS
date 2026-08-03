import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_admin
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.iiko import (
    IikoMappingStatus,
    IikoProductMapping,
    IikoRawEntity,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
    IikoUnitMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import (
    Department,
    LegalContour,
    SupplyProduct,
    SupplyRequest,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyUnit,
)
from app.models.user import User
from app.supply.iiko_stock import (
    _locked_request_statement,
    get_stock_check,
    list_allowed_sources,
)


class SupplyIikoStockTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        self.previous_tenant_id = settings.default_tenant_id
        settings.default_tenant_id = "tenant-a"
        self.engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        for table in (
            User.__table__,
            SupplyUnit.__table__,
            Department.__table__,
            SupplyRequestDirection.__table__,
            SupplyProduct.__table__,
            IikoSyncRun.__table__,
            IikoRawEntity.__table__,
            IikoProductMapping.__table__,
            IikoUnitMapping.__table__,
            IikoWarehouseMapping.__table__,
            SupplyRequest.__table__,
            SupplyRequestLine.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        admin = User(
            id=1,
            username="admin",
            display_name="Администратор",
            hashed_password="unused",
            is_active=True,
            is_admin=True,
        )

        def override_db():
            with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_admin] = lambda: admin
        self.client = TestClient(app)

        self.iiko_product_id = uuid4()
        self.iiko_unit_id = uuid4()
        self.iiko_warehouse_id = uuid4()
        self.initial_sync_at = datetime(2026, 8, 3, 6, tzinfo=timezone.utc)
        with self.sessions.begin() as session:
            session.add(admin)
            unit = SupplyUnit(
                tenant_id="tenant-a",
                code="KG",
                name_ru="Килограмм",
                short_name_ru="кг",
                allows_fraction=True,
            )
            department = Department(
                tenant_id="tenant-a",
                code="M15",
                name="М15",
                legal_contour=LegalContour.IP,
            )
            direction = SupplyRequestDirection(
                tenant_id="tenant-a",
                code="MAIN",
                name="Продукты",
            )
            product = SupplyProduct(
                tenant_id="tenant-a",
                name="Молоко",
                normalized_name="молоко",
                default_unit=unit,
            )
            session.add_all([unit, department, direction, product])
            session.flush()
            source = IikoWarehouseMapping(
                tenant_id="tenant-a",
                iiko_warehouse_id=self.iiko_warehouse_id,
                destination_type=IikoWarehouseDestinationType.SOURCE,
                role=IikoWarehouseRole.MAIN,
                legal_contour=LegalContour.IP,
                status=IikoMappingStatus.CONFIRMED,
                source_name="Источник продуктов",
            )
            request = SupplyRequest(
                tenant_id="tenant-a",
                public_number="REQ-1",
                department=department,
                direction=direction,
                status="IN_REVIEW",
                source_type="INTERNAL",
                raw_input="Молоко 5 кг",
            )
            line = SupplyRequestLine(
                request=request,
                position=1,
                raw_text="Молоко 5 кг",
                parsed_name="Молоко",
                product=product,
                requested_unit=unit,
                quantity=Decimal("5"),
                match_status="MATCHED",
                match_method="MANUAL",
            )
            session.add_all([source, request, line])
            session.flush()
            request.iiko_source_warehouse_mapping_id = source.id
            self.request_id = request.id
            self.unit_id = unit.id
            self.source_id = source.id
            session.add_all([
                IikoProductMapping(
                    tenant_id="tenant-a",
                    iiko_product_id=self.iiko_product_id,
                    eos_product_id=product.id,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="Молоко iiko",
                    source_unit_id=self.iiko_unit_id,
                ),
                IikoUnitMapping(
                    tenant_id="tenant-a",
                    iiko_unit_id=self.iiko_unit_id,
                    eos_unit_id=unit.id,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="кг",
                ),
            ])
            run = IikoSyncRun(
                tenant_id="tenant-a",
                sync_type=IikoSyncType.STOCK_BALANCES,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
                finished_at=self.initial_sync_at,
                parameters={
                    "warehouse_external_ids": [str(self.iiko_warehouse_id)],
                },
            )
            session.add(run)
            session.flush()
            session.add(IikoRawEntity(
                tenant_id="tenant-a",
                sync_run_id=run.id,
                entity_type="stock_balance",
                external_id=f"{self.iiko_warehouse_id}:{self.iiko_product_id}",
                organization_external_id=str(self.iiko_warehouse_id),
                payload={
                    "store": str(self.iiko_warehouse_id),
                    "product": str(self.iiko_product_id),
                    "amount": "8.000",
                },
                payload_hash="stock-8",
                is_active=True,
            ))

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        settings.default_tenant_id = self.previous_tenant_id
        self.engine.dispose()

    def test_allowed_sources_require_confirmed_source_contour_and_product_role(
        self,
    ) -> None:
        with self.sessions.begin() as session:
            request = session.get(SupplyRequest, self.request_id)
            session.add_all([
                IikoWarehouseMapping(
                    tenant_id="tenant-a",
                    iiko_warehouse_id=uuid4(),
                    destination_type=IikoWarehouseDestinationType.SOURCE,
                    role=IikoWarehouseRole.PACKAGING,
                    legal_contour=LegalContour.IP,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="Источник упаковки",
                ),
                IikoWarehouseMapping(
                    tenant_id="tenant-a",
                    iiko_warehouse_id=uuid4(),
                    destination_type=IikoWarehouseDestinationType.SOURCE,
                    role=IikoWarehouseRole.MAIN,
                    legal_contour=LegalContour.OOO,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="Другой контур",
                ),
                IikoWarehouseMapping(
                    tenant_id="tenant-a",
                    iiko_warehouse_id=uuid4(),
                    destination_type=IikoWarehouseDestinationType.SOURCE,
                    role=IikoWarehouseRole.MAIN,
                    legal_contour=LegalContour.IP,
                    status=IikoMappingStatus.SUGGESTED,
                    source_name="Не подтверждён",
                ),
            ])
            session.flush()
            allowed = list_allowed_sources(session, request)
            self.assertEqual([item.id for item in allowed], [self.source_id])

    def test_household_allows_only_explicit_household_source_role(self) -> None:
        with self.sessions.begin() as session:
            request = session.get(SupplyRequest, self.request_id)
            request.direction.code = "HOUSEHOLD"
            request.direction.name = "Хозяйственный"
            household_source = IikoWarehouseMapping(
                tenant_id="tenant-a",
                iiko_warehouse_id=uuid4(),
                destination_type=IikoWarehouseDestinationType.SOURCE,
                role=IikoWarehouseRole.HOUSEHOLD,
                legal_contour=LegalContour.IP,
                status=IikoMappingStatus.CONFIRMED,
                source_name="Источник хозтоваров",
            )
            packaging_source = IikoWarehouseMapping(
                tenant_id="tenant-a",
                iiko_warehouse_id=uuid4(),
                destination_type=IikoWarehouseDestinationType.SOURCE,
                role=IikoWarehouseRole.PACKAGING,
                legal_contour=LegalContour.IP,
                status=IikoMappingStatus.CONFIRMED,
                source_name="Источник упаковки",
            )
            session.add_all([household_source, packaging_source])
            session.flush()
            allowed = list_allowed_sources(session, request)
            self.assertEqual(
                [item.id for item in allowed],
                [household_source.id],
            )

    def test_put_selects_source_with_base_request_postgresql_lock(self) -> None:
        statement = _locked_request_statement(
            tenant_id="tenant-a",
            request_id=self.request_id,
        )
        sql = str(statement.compile(dialect=postgresql.dialect())).upper()
        self.assertIn("FOR UPDATE OF SUPPLY_REQUESTS", sql)
        self.assertNotIn(" JOIN ", sql)

        with self.sessions.begin() as session:
            replacement = IikoWarehouseMapping(
                tenant_id="tenant-a",
                iiko_warehouse_id=uuid4(),
                destination_type=IikoWarehouseDestinationType.SOURCE,
                role=IikoWarehouseRole.MAIN,
                legal_contour=LegalContour.IP,
                status=IikoMappingStatus.CONFIRMED,
                source_name="Второй источник продуктов",
            )
            session.add(replacement)
            session.flush()
            replacement_id = replacement.id

        response = self.client.put(
            f"/supply/requests/{self.request_id}/iiko-source-warehouse",
            json={"mapping_id": str(replacement_id), "expected_version": 1},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["selected_source"]["mapping_id"],
            str(replacement_id),
        )
        with self.sessions() as session:
            request = session.get(SupplyRequest, self.request_id)
            self.assertEqual(request.iiko_source_warehouse_mapping_id, replacement_id)
            self.assertEqual(request.version, 2)

    def test_terminal_request_rejects_source_change(self) -> None:
        with self.sessions.begin() as session:
            request = session.get(SupplyRequest, self.request_id)
            request.status = "FULFILLED"
            original_version = request.version

        response = self.client.put(
            f"/supply/requests/{self.request_id}/iiko-source-warehouse",
            json={"mapping_id": str(self.source_id), "expected_version": 1},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "SUPPLY_IIKO_SOURCE_TERMINAL_REQUEST",
        )
        with self.sessions() as session:
            request = session.get(SupplyRequest, self.request_id)
            self.assertEqual(request.version, original_version)

    def test_uses_latest_finished_succeeded_run_for_selected_source(self) -> None:
        other_warehouse_id = uuid4()
        with self.sessions.begin() as session:
            runs = [
                (
                    IikoSyncStatus.SUCCEEDED,
                    self.initial_sync_at + timedelta(hours=1),
                    self.iiko_warehouse_id,
                    "10.000",
                    "stock-10",
                ),
                (
                    IikoSyncStatus.PARTIALLY_SUCCEEDED,
                    self.initial_sync_at + timedelta(hours=2),
                    self.iiko_warehouse_id,
                    "99.000",
                    "stock-partial",
                ),
                (
                    IikoSyncStatus.SUCCEEDED,
                    self.initial_sync_at + timedelta(hours=3),
                    other_warehouse_id,
                    "77.000",
                    "stock-other",
                ),
                (
                    IikoSyncStatus.SUCCEEDED,
                    None,
                    self.iiko_warehouse_id,
                    "123.000",
                    "stock-unfinished",
                ),
            ]
            for status, finished_at, warehouse_id, amount, payload_hash in runs:
                run = IikoSyncRun(
                    tenant_id="tenant-a",
                    sync_type=IikoSyncType.STOCK_BALANCES,
                    status=status,
                    source_api_type="iiko_server",
                    finished_at=finished_at,
                    parameters={
                        "warehouse_external_ids": [str(warehouse_id)],
                    },
                )
                session.add(run)
                session.flush()
                session.add(IikoRawEntity(
                    tenant_id="tenant-a",
                    sync_run_id=run.id,
                    entity_type="stock_balance",
                    external_id=f"{warehouse_id}:{self.iiko_product_id}",
                    organization_external_id=str(warehouse_id),
                    payload={
                        "store": str(warehouse_id),
                        "product": str(self.iiko_product_id),
                        "amount": amount,
                    },
                    payload_hash=payload_hash,
                    is_active=True,
                ))

        with self.sessions() as session:
            result = get_stock_check(
                session,
                tenant_id="tenant-a",
                request_id=self.request_id,
            )
            self.assertEqual(result.lines[0].stock_quantity, Decimal("10.000"))
            last_sync_at = result.last_sync_at
            if last_sync_at is not None and last_sync_at.tzinfo is None:
                last_sync_at = last_sync_at.replace(tzinfo=timezone.utc)
            self.assertEqual(
                last_sync_at,
                self.initial_sync_at + timedelta(hours=1),
            )

    def test_reports_sufficient_balance_from_selected_source(self) -> None:
        with self.sessions() as session:
            result = get_stock_check(
                session,
                tenant_id="tenant-a",
                request_id=self.request_id,
            )
            self.assertEqual(result.lines[0].stock_quantity, Decimal("8.000"))
            self.assertTrue(result.lines[0].is_sufficient)
            self.assertEqual(result.lines[0].deficit, Decimal("0"))
            self.assertIsNone(result.lines[0].unavailable_reason)

    def test_unit_id_mismatch_makes_calculation_unavailable(self) -> None:
        with self.sessions.begin() as session:
            mapping = session.scalar(select(IikoUnitMapping))
            mapping.eos_unit_id = uuid4()
        with self.sessions() as session:
            result = get_stock_check(
                session,
                tenant_id="tenant-a",
                request_id=self.request_id,
            )
            self.assertIsNone(result.lines[0].stock_quantity)
            self.assertIsNone(result.lines[0].is_sufficient)
            self.assertEqual(
                result.lines[0].unavailable_reason,
                "Единица заявки не совпадает с unit_id iiko",
            )


if __name__ == "__main__":
    unittest.main()
