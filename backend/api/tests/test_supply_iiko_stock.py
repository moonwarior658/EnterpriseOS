import os
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
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
from app.models.supply import (
    Department,
    LegalContour,
    SupplyDepartmentProductCorrection,
    SupplyDepartmentProductMapping,
    SupplyDepartmentProductMappingAuditEvent,
    SupplyProduct,
    SupplyProductAlias,
    SupplyProductCategory,
    SupplyProductSourceMapping,
    SupplyProductSourceRole,
    SupplyProcurementNeed,
    SupplyProcurementNeedReason,
    SupplyProcurementNeedSourceType,
    SupplyProcurementNeedStatus,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyRequestLineDebtLink,
    SupplyLineAllocation,
    SupplyStorageZone,
    SupplyDepartmentDebt,
    SupplyDepartmentDebtEvent,
    SupplyUnit,
    SupplyStockCalculation,
    SupplyStockCalculationAuditEvent,
    SupplyStockCalculationLine,
)
from app.models.user import User
from app.supply.iiko_stock import (
    _locked_request_statement,
    get_stock_check,
    list_allowed_sources,
)
from app.supply.procurement_needs import reconcile_department_debt_need


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
            SupplyRequestCycle.__table__,
            SupplyProductCategory.__table__,
            SupplyStorageZone.__table__,
            SupplyProduct.__table__,
            SupplyProductAlias.__table__,
            SupplyDepartmentProductMapping.__table__,
            SupplyDepartmentProductMappingAuditEvent.__table__,
            IikoSyncRun.__table__,
            IikoRawEntity.__table__,
            IikoProductMapping.__table__,
            IikoUnitMapping.__table__,
            IikoWarehouseMapping.__table__,
            IikoStockBalanceSnapshotSource.__table__,
            IikoStockBalanceSnapshotLine.__table__,
            SupplyProductSourceMapping.__table__,
            SupplyRequest.__table__,
            SupplyRequestLine.__table__,
            SupplyDepartmentProductCorrection.__table__,
            SupplyLineAllocation.__table__,
            SupplyDepartmentDebt.__table__,
            SupplyDepartmentDebtEvent.__table__,
            SupplyRequestLineDebtLink.__table__,
            SupplyStockCalculation.__table__,
            SupplyStockCalculationLine.__table__,
            SupplyProcurementNeed.__table__,
            SupplyStockCalculationAuditEvent.__table__,
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
            tenant_id="tenant-a",
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
                is_active=True,
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
                is_deleted=False,
            )
            request = SupplyRequest(
                tenant_id="tenant-a",
                public_number="REQ-1",
                department=department,
                direction=direction,
                status="IN_REVIEW",
                source_type="INTERNAL",
                raw_input="Молоко 5 кг",
                need_date=datetime(2026, 8, 10, tzinfo=timezone.utc).date(),
            )
            line = SupplyRequestLine(
                tenant_id="tenant-a",
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
            self.department_id = department.id
            self.unit_id = unit.id
            self.source_id = source.id
            self.product_id = product.id
            self.line_id = line.id
            session.add(SupplyProductSourceMapping(
                tenant_id="tenant-a",
                eos_product_id=product.id,
                legal_contour=LegalContour.IP,
                role=SupplyProductSourceRole.MAIN,
                source_warehouse_mapping_id=source.id,
                assigned_by_user_id=admin.id,
            ))
            session.add_all([
                IikoProductMapping(
                    tenant_id="tenant-a",
                    iiko_product_id=self.iiko_product_id,
                    eos_product_id=product.id,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name="Т Молоко iiko",
                    source_unit_id=self.iiko_unit_id,
                    is_deleted=False,
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
                sync_type=IikoSyncType.STOCK_BALANCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
                finished_at=self.initial_sync_at,
                parameters={
                    "snapshot_at": self.initial_sync_at.isoformat(),
                    "completed_source_warehouse_mapping_ids": [str(source.id)],
                },
            )
            session.add(run)
            session.flush()
            session.add(IikoStockBalanceSnapshotSource(
                tenant_id="tenant-a",
                sync_run_id=run.id,
                department_id=department.id,
                source_warehouse_mapping_id=source.id,
                snapshot_at=self.initial_sync_at,
                status=IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
            ))
            session.flush()
            session.add(IikoStockBalanceSnapshotLine(
                tenant_id="tenant-a",
                sync_run_id=run.id,
                department_id=department.id,
                source_warehouse_mapping_id=source.id,
                iiko_warehouse_id=self.iiko_warehouse_id,
                iiko_product_id=self.iiko_product_id,
                iiko_unit_id=self.iiko_unit_id,
                quantity=Decimal("8.000"),
                snapshot_at=self.initial_sync_at,
            ))

    def _add_stock_sync(
        self,
        amount: str,
        finished_at: datetime,
        *,
        run_id: UUID | None = None,
        started_at: datetime | None = None,
    ) -> None:
        with self.sessions.begin() as session:
            run = IikoSyncRun(
                id=run_id or uuid4(),
                tenant_id="tenant-a",
                sync_type=IikoSyncType.STOCK_BALANCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
                started_at=started_at or finished_at,
                finished_at=finished_at,
                parameters={
                    "snapshot_at": finished_at.isoformat(),
                    "completed_source_warehouse_mapping_ids": [str(self.source_id)],
                },
            )
            session.add(run)
            session.flush()
            session.add(IikoStockBalanceSnapshotSource(
                tenant_id="tenant-a",
                sync_run_id=run.id,
                department_id=self.department_id,
                source_warehouse_mapping_id=self.source_id,
                snapshot_at=finished_at,
                status=IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
            ))
            session.flush()
            session.add(IikoStockBalanceSnapshotLine(
                tenant_id="tenant-a",
                sync_run_id=run.id,
                department_id=self.department_id,
                source_warehouse_mapping_id=self.source_id,
                iiko_warehouse_id=self.iiko_warehouse_id,
                iiko_product_id=self.iiko_product_id,
                iiko_unit_id=self.iiko_unit_id,
                quantity=Decimal(amount),
                snapshot_at=finished_at,
            ))

    def _create_open_need(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": calculated["id"],
                "expected_revision": calculated["revision"],
                "expected_version": calculated["version"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

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
                source_mapping_id = (
                    self.source_id
                    if warehouse_id == self.iiko_warehouse_id
                    else uuid4()
                )
                snapshot_at = finished_at or self.initial_sync_at + timedelta(hours=4)
                run = IikoSyncRun(
                    tenant_id="tenant-a",
                    sync_type=IikoSyncType.STOCK_BALANCE_SNAPSHOT,
                    status=status,
                    source_api_type="iiko_server",
                    finished_at=finished_at,
                    parameters={
                        "snapshot_at": snapshot_at.isoformat(),
                        "completed_source_warehouse_mapping_ids": [
                            str(source_mapping_id)
                        ],
                    },
                )
                session.add(run)
                session.flush()
                session.add(IikoStockBalanceSnapshotSource(
                    tenant_id="tenant-a",
                    sync_run_id=run.id,
                    department_id=self.department_id,
                    source_warehouse_mapping_id=source_mapping_id,
                    snapshot_at=snapshot_at,
                    status=IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
                ))
                session.flush()
                session.add(IikoStockBalanceSnapshotLine(
                    tenant_id="tenant-a",
                    sync_run_id=run.id,
                    department_id=self.department_id,
                    source_warehouse_mapping_id=source_mapping_id,
                    iiko_warehouse_id=warehouse_id,
                    iiko_product_id=self.iiko_product_id,
                    iiko_unit_id=self.iiko_unit_id,
                    quantity=Decimal(amount),
                    snapshot_at=snapshot_at,
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

    def test_calculation_available_more_than_requested(self) -> None:
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(Decimal(line["requested_quantity"]), Decimal("5"))
        self.assertEqual(Decimal(line["available_quantity"]), Decimal("8"))
        self.assertEqual(Decimal(line["transferable_quantity"]), Decimal("5"))
        self.assertEqual(Decimal(line["deficit_quantity"]), Decimal("0"))

    def test_preliminary_does_not_create_procurement_need(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as session:
            self.assertIsNone(session.scalar(select(SupplyProcurementNeed)))

    def test_confirmed_deficit_creates_and_revisions_update_open_need(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        first = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        confirmed = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": first["id"],
                "expected_revision": first["revision"],
                "expected_version": first["version"],
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        with self.sessions() as session:
            need = session.scalar(select(SupplyProcurementNeed))
            first_need_id = need.id
            self.assertEqual(need.source_type.value, "REQUEST_LINE")
            self.assertEqual(need.supply_request_line_id, self.line_id)
            self.assertEqual(need.quantity, Decimal("2.000"))
            self.assertEqual(need.product_id, self.product_id)
            self.assertEqual(need.unit_id, self.unit_id)
            self.assertEqual(need.need_date.isoformat(), "2026-08-10")
            self.assertEqual(need.version, 1)

        self._add_stock_sync(
            "6.000", self.initial_sync_at + timedelta(hours=1)
        )
        second = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        reconfirmed = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": second["id"],
                "expected_revision": second["revision"],
                "expected_version": second["version"],
            },
        )
        self.assertEqual(reconfirmed.status_code, 200, reconfirmed.text)
        with self.sessions() as session:
            needs = session.scalars(select(SupplyProcurementNeed)).all()
            self.assertEqual(len(needs), 1)
            self.assertEqual(needs[0].id, first_need_id)
            self.assertEqual(needs[0].quantity, Decimal("4.000"))
            self.assertEqual(needs[0].version, 2)
            self.assertEqual(
                needs[0].basis_stock_calculation_line_id,
                UUID(second["groups"][0]["lines"][0]["id"]),
            )

    def test_repeated_confirmation_does_not_duplicate_open_need(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        payload = {
            "calculation_id": calculated["id"],
            "expected_revision": calculated["revision"],
            "expected_version": calculated["version"],
        }
        first = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json=payload,
        )
        self.assertEqual(first.status_code, 200, first.text)
        payload["expected_version"] = first.json()["version"]
        repeated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json=payload,
        )
        self.assertEqual(repeated.status_code, 409, repeated.text)
        with self.sessions() as session:
            needs = session.scalars(select(SupplyProcurementNeed)).all()
            self.assertEqual(len(needs), 1)
            self.assertEqual(needs[0].status.value, "OPEN")

    def test_confirmation_is_tenant_isolated(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        other_admin = User(
            id=2,
            username="other-admin",
            display_name="Другой администратор",
            hashed_password="unused",
            is_active=True,
            is_admin=True,
            tenant_id="tenant-b",
        )
        app.dependency_overrides[get_current_admin] = lambda: other_admin
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": calculated["id"],
                "expected_revision": calculated["revision"],
                "expected_version": calculated["version"],
            },
        )
        self.assertEqual(response.status_code, 404, response.text)
        with self.sessions() as session:
            calculation = session.get(
                SupplyStockCalculation, UUID(calculated["id"])
            )
            self.assertEqual(calculation.status.value, "PRELIMINARY")
            self.assertIsNone(session.scalar(select(SupplyProcurementNeed)))

    def test_zero_deficit_closes_open_need_and_later_deficit_creates_history(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        for amount in ("8.000", "12.000", "7.000"):
            if amount != "8.000":
                offset = 1 if amount == "12.000" else 2
                self._add_stock_sync(
                    amount, self.initial_sync_at + timedelta(hours=offset)
                )
            calculated = self.client.post(
                f"/supply/requests/{self.request_id}/stock-calculation/calculate"
            ).json()
            response = self.client.post(
                f"/supply/requests/{self.request_id}/stock-calculation/confirm",
                json={
                    "calculation_id": calculated["id"],
                    "expected_revision": calculated["revision"],
                    "expected_version": calculated["version"],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as session:
            needs = session.scalars(
                select(SupplyProcurementNeed).order_by(SupplyProcurementNeed.created_at)
            ).all()
            self.assertEqual(len(needs), 2)
            self.assertEqual(needs[0].status.value, "CLOSED")
            self.assertIsNotNone(needs[0].closed_at)
            self.assertEqual(needs[1].status.value, "OPEN")
            self.assertEqual(needs[1].quantity, Decimal("3.000"))

    def test_request_without_need_date_does_not_create_procurement_need(self) -> None:
        with self.sessions.begin() as session:
            request = session.get(SupplyRequest, self.request_id)
            request.need_date = None
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": calculated["id"],
                "expected_revision": calculated["revision"],
                "expected_version": calculated["version"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as session:
            self.assertIsNone(session.scalar(select(SupplyProcurementNeed)))

    def test_quantity_mutation_closes_open_procurement_need(self) -> None:
        self._create_open_need()
        response = self.client.patch(
            f"/supply/requests/{self.request_id}/lines/{self.line_id}/working-values",
            json={
                "request_version": 1,
                "working_name": "Молоко",
                "requested_quantity": "11.000",
                "send_quantity": "0",
                "requested_unit_id": str(self.unit_id),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as session:
            need = session.scalar(select(SupplyProcurementNeed))
            self.assertEqual(need.status.value, "CLOSED")

    def test_product_mutation_closes_open_procurement_need(self) -> None:
        self._create_open_need()
        with self.sessions.begin() as session:
            replacement = SupplyProduct(
                tenant_id="tenant-a",
                name="Сливки",
                normalized_name="сливки",
                default_unit_id=self.unit_id,
                is_active=True,
            )
            session.add(replacement)
            session.flush()
            replacement_id = replacement.id
        response = self.client.post(
            f"/supply/requests/{self.request_id}/lines/{self.line_id}/match",
            json={
                "expected_version": 1,
                "action": "MATCH",
                "product_id": str(replacement_id),
                "unit_id": str(self.unit_id),
                "quantity": "10.000",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as session:
            need = session.scalar(select(SupplyProcurementNeed))
            self.assertEqual(need.status.value, "CLOSED")

    def test_unit_mutation_closes_open_procurement_need(self) -> None:
        self._create_open_need()
        with self.sessions.begin() as session:
            liters = SupplyUnit(
                tenant_id="tenant-a",
                code="L",
                name_ru="Литр",
                short_name_ru="л",
                allows_fraction=True,
            )
            session.add(liters)
            session.flush()
            liters_id = liters.id
        response = self.client.patch(
            f"/supply/requests/{self.request_id}/lines/{self.line_id}/working-values",
            json={
                "request_version": 1,
                "working_name": "Молоко",
                "requested_quantity": "10.000",
                "send_quantity": "0",
                "requested_unit_id": str(liters_id),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as session:
            need = session.scalar(select(SupplyProcurementNeed))
            self.assertEqual(need.status.value, "CLOSED")

    def test_need_date_mutation_closes_open_procurement_need(self) -> None:
        self._create_open_need()
        response = self.client.patch(
            f"/supply/requests/{self.request_id}/need-date",
            json={"expected_version": 1, "need_date": "2026-08-11"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["need_date"], "2026-08-11")
        with self.sessions() as session:
            need = session.scalar(select(SupplyProcurementNeed))
            self.assertEqual(need.status.value, "CLOSED")

    def test_reconciliation_failure_rolls_back_confirmation(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        with patch(
            "app.supply.stock_calculation.reconcile_confirmed_stock_calculation_needs",
            side_effect=RuntimeError("reconcile failed"),
        ), self.assertRaises(RuntimeError):
            self.client.post(
                f"/supply/requests/{self.request_id}/stock-calculation/confirm",
                json={
                    "calculation_id": calculated["id"],
                    "expected_revision": calculated["revision"],
                    "expected_version": calculated["version"],
                },
            )
        with self.sessions() as session:
            calculation = session.get(
                SupplyStockCalculation, UUID(calculated["id"])
            )
            self.assertEqual(calculation.status.value, "PRELIMINARY")
            self.assertIsNone(session.scalar(select(SupplyProcurementNeed)))

    def test_procurement_need_source_check_and_open_uniqueness(self) -> None:
        with self.sessions() as session:
            session.add(SupplyProcurementNeed(
                tenant_id="tenant-a",
                source_type=SupplyProcurementNeedSourceType.REQUEST_LINE,
                supply_request_line_id=self.line_id,
                basis_stock_calculation_line_id=None,
                product_id=self.product_id,
                unit_id=self.unit_id,
                quantity=Decimal("1"),
                need_date=datetime(2026, 8, 10).date(),
                status=SupplyProcurementNeedStatus.OPEN,
                reason=SupplyProcurementNeedReason.INTERNAL_STOCK_DEFICIT,
            ))
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

        self._create_open_need()
        with self.sessions() as session:
            current = session.scalar(select(SupplyProcurementNeed))
            session.add(SupplyProcurementNeed(
                tenant_id="tenant-a",
                source_type=SupplyProcurementNeedSourceType.REQUEST_LINE,
                supply_request_line_id=self.line_id,
                basis_stock_calculation_line_id=(
                    current.basis_stock_calculation_line_id
                ),
                product_id=self.product_id,
                unit_id=self.unit_id,
                quantity=Decimal("1"),
                need_date=datetime(2026, 8, 10).date(),
                status=SupplyProcurementNeedStatus.OPEN,
                reason=SupplyProcurementNeedReason.INTERNAL_STOCK_DEFICIT,
            ))
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_debt_need_requires_trusted_date_and_included_debt_is_closed(self) -> None:
        with self.sessions.begin() as session:
            debt = SupplyDepartmentDebt(
                tenant_id="tenant-a",
                department_id=self.department_id,
                product_id=self.product_id,
                working_name="Молоко",
                unit_id=self.unit_id,
                outstanding_quantity=Decimal("2"),
                original_quantity=Decimal("2"),
                status="ACTIVE",
                first_request_id=self.request_id,
                latest_request_id=self.request_id,
                first_request_line_id=self.line_id,
                latest_request_line_id=self.line_id,
                opened_at=datetime.now(timezone.utc),
            )
            session.add(debt)
            session.flush()
            debt_id = debt.id
            self.assertIsNone(reconcile_department_debt_need(
                session, debt=debt, need_date=None
            ))
            need = reconcile_department_debt_need(
                session,
                debt=debt,
                need_date=datetime(2026, 8, 12).date(),
            )
            self.assertIsNotNone(need)
        with self.sessions.begin() as session:
            debt = session.get(SupplyDepartmentDebt, debt_id)
            session.add(SupplyRequestLineDebtLink(
                request_line_id=self.line_id,
                tenant_id="tenant-a",
                included_debt_id=debt.id,
                included_quantity=Decimal("2"),
                inclusion_confirmed=True,
            ))
        with self.sessions.begin() as session:
            debt = session.get(SupplyDepartmentDebt, debt_id)
            self.assertIsNone(reconcile_department_debt_need(
                session,
                debt=debt,
                need_date=datetime(2026, 8, 12).date(),
            ))
        with self.sessions() as session:
            need = session.scalar(select(SupplyProcurementNeed))
            self.assertEqual(need.status.value, "CLOSED")

    def test_send_quantity_does_not_change_or_invalidate_stock_plan(self) -> None:
        with self.sessions.begin() as session:
            request_line = session.get(SupplyRequestLine, self.line_id)
            request_line.quantity = Decimal("10")
            stock_line = session.scalar(select(IikoStockBalanceSnapshotLine))
            stock_line.quantity = Decimal("20")

        preliminary = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(preliminary.status_code, 200, preliminary.text)
        preliminary_body = preliminary.json()
        preliminary_line = preliminary_body["groups"][0]["lines"][0]
        self.assertEqual(
            Decimal(preliminary_line["requested_quantity"]), Decimal("10")
        )
        self.assertEqual(
            Decimal(preliminary_line["transferable_quantity"]), Decimal("10")
        )

        with self.sessions.begin() as session:
            request_line = session.get(SupplyRequestLine, self.line_id)
            request_line.send_quantity = Decimal("8")

        still_preliminary = self.client.get(
            f"/supply/requests/{self.request_id}/stock-calculation"
        )
        self.assertEqual(
            still_preliminary.status_code, 200, still_preliminary.text
        )
        self.assertEqual(still_preliminary.json()["id"], preliminary_body["id"])
        self.assertEqual(
            Decimal(
                still_preliminary.json()["groups"][0]["lines"][0]
                ["requested_quantity"]
            ),
            Decimal("10"),
        )

        confirmed = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": preliminary_body["id"],
                "expected_revision": preliminary_body["revision"],
                "expected_version": preliminary_body["version"],
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["status"], "CONFIRMED")

        current = self.client.get(
            f"/supply/requests/{self.request_id}/stock-calculation"
        )
        self.assertEqual(current.status_code, 200, current.text)
        current_line = current.json()["groups"][0]["lines"][0]
        self.assertEqual(current.json()["status"], "CONFIRMED")
        self.assertEqual(
            Decimal(current_line["requested_quantity"]), Decimal("10")
        )
        self.assertEqual(
            Decimal(current_line["transferable_quantity"]), Decimal("10")
        )
        with self.sessions() as session:
            request_line = session.get(SupplyRequestLine, self.line_id)
            self.assertEqual(request_line.send_quantity, Decimal("8"))
            self.assertEqual(
                request_line.quantity - request_line.send_quantity,
                Decimal("2"),
            )

    def test_product_change_invalidates_preliminary_calculation(self) -> None:
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(calculated.status_code, 200, calculated.text)
        with self.sessions.begin() as session:
            unit = session.get(SupplyUnit, self.unit_id)
            replacement = SupplyProduct(
                tenant_id="tenant-a",
                name="Молоко для кофе",
                normalized_name="молоко для кофе",
                default_unit=unit,
                is_active=True,
            )
            session.add(replacement)
            session.flush()
            line = session.get(SupplyRequestLine, self.line_id)
            line.product_id = replacement.id

        current = self.client.get(
            f"/supply/requests/{self.request_id}/stock-calculation"
        )
        self.assertEqual(current.status_code, 200, current.text)
        self.assertIsNone(current.json())

    def test_requested_quantity_and_unit_changes_invalidate_preliminary(
        self,
    ) -> None:
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(calculated.status_code, 200, calculated.text)
        with self.sessions.begin() as session:
            line = session.get(SupplyRequestLine, self.line_id)
            line.quantity = Decimal("6")
        current = self.client.get(
            f"/supply/requests/{self.request_id}/stock-calculation"
        )
        self.assertIsNone(current.json())

        recalculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(recalculated.status_code, 200, recalculated.text)
        with self.sessions.begin() as session:
            liters = SupplyUnit(
                tenant_id="tenant-a",
                code="L",
                name_ru="Литр",
                short_name_ru="л",
                allows_fraction=True,
            )
            session.add(liters)
            session.flush()
            line = session.get(SupplyRequestLine, self.line_id)
            line.requested_unit_id = liters.id
        current = self.client.get(
            f"/supply/requests/{self.request_id}/stock-calculation"
        )
        self.assertEqual(current.status_code, 200, current.text)
        self.assertIsNone(current.json())

    def test_calculation_available_less_than_requested(self) -> None:
        self._add_stock_sync(
            "3.000", self.initial_sync_at + timedelta(hours=1)
        )
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(Decimal(line["transferable_quantity"]), Decimal("3"))
        self.assertEqual(Decimal(line["deficit_quantity"]), Decimal("2"))

    def test_negative_stock_is_preserved_but_not_transferable(self) -> None:
        with self.sessions.begin() as session:
            stock_line = session.scalar(select(IikoStockBalanceSnapshotLine))
            stock_line.quantity = Decimal("-2.000000")
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(Decimal(line["available_quantity"]), Decimal("-2"))
        self.assertEqual(Decimal(line["transferable_quantity"]), Decimal("0"))
        self.assertEqual(Decimal(line["deficit_quantity"]), Decimal("5"))

    def test_missing_product_in_succeeded_source_snapshot_means_zero(self) -> None:
        with self.sessions.begin() as session:
            session.delete(session.scalar(select(IikoStockBalanceSnapshotLine)))

        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )

        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(Decimal(line["available_quantity"]), Decimal("0"))
        self.assertEqual(Decimal(line["transferable_quantity"]), Decimal("0"))
        self.assertEqual(Decimal(line["deficit_quantity"]), Decimal("5"))
        self.assertIsNone(line["unavailable_reason"])

    def test_missing_succeeded_source_snapshot_remains_blocked(self) -> None:
        with self.sessions.begin() as session:
            source_snapshot = session.scalar(
                select(IikoStockBalanceSnapshotSource)
            )
            source_snapshot.status = IikoStockBalanceSnapshotSourceStatus.FAILED

        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )

        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(
            line["unavailable_reason"],
            "Нет успешного снимка остатков iiko для SOURCE",
        )
        self.assertIsNone(line["available_quantity"])

    def test_partially_succeeded_snapshot_remains_blocked(self) -> None:
        with self.sessions.begin() as session:
            run = session.scalar(select(IikoSyncRun))
            run.status = IikoSyncStatus.PARTIALLY_SUCCEEDED

        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )

        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(
            line["unavailable_reason"],
            "Нет успешного снимка остатков iiko для SOURCE",
        )
        self.assertIsNone(line["available_quantity"])

    def test_calculation_unit_mismatch_remains_blocked(self) -> None:
        with self.sessions.begin() as session:
            mapping = session.scalar(select(IikoUnitMapping))
            mapping.eos_unit_id = uuid4()

        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )

        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(
            line["unavailable_reason"],
            "Единица заявки не совпадает с unit_id iiko",
        )
        self.assertIsNone(line["available_quantity"])

        with self.sessions.begin() as session:
            mapping = session.scalar(select(IikoUnitMapping))
            mapping.eos_unit_id = self.unit_id
        fixed = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(fixed.status_code, 200, fixed.text)
        fixed_line = fixed.json()["groups"][0]["lines"][0]
        self.assertIsNone(fixed_line["unavailable_reason"])
        self.assertEqual(Decimal(fixed_line["transferable_quantity"]), Decimal("5"))

    def test_missing_product_mapping_remains_blocked(self) -> None:
        with self.sessions.begin() as session:
            mapping = session.scalar(select(IikoProductMapping))
            mapping.status = IikoMappingStatus.SUGGESTED

        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )

        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(
            line["unavailable_reason"],
            "Нет подтверждённого mapping товара iiko",
        )
        self.assertIsNone(line["available_quantity"])

    def test_manual_transferable_decrease_is_persisted(self) -> None:
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        calculation = calculated.json()
        line = calculation["groups"][0]["lines"][0]
        response = self.client.patch(
            f"/supply/requests/{self.request_id}/stock-calculation/lines/{line['id']}",
            json={
                "calculation_id": calculation["id"],
                "expected_revision": calculation["revision"],
                "expected_version": calculation["version"],
                "expected_line_version": line["version"],
                "quantity": "2.000",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["groups"][0]["lines"][0]
        self.assertEqual(Decimal(line["transferable_quantity"]), Decimal("2"))
        self.assertEqual(Decimal(line["deficit_quantity"]), Decimal("3"))
        self.assertEqual(response.json()["version"], calculation["version"] + 1)
        self.assertEqual(line["version"], 2)

    def test_stale_patch_returns_version_conflict(self) -> None:
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        line = calculated["groups"][0]["lines"][0]
        payload = {
            "calculation_id": calculated["id"],
            "expected_revision": calculated["revision"],
            "expected_version": calculated["version"],
            "expected_line_version": line["version"],
            "quantity": "2.000",
        }
        first = self.client.patch(
            f"/supply/requests/{self.request_id}/stock-calculation/lines/{line['id']}",
            json=payload,
        )
        stale = self.client.patch(
            f"/supply/requests/{self.request_id}/stock-calculation/lines/{line['id']}",
            json=payload,
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["code"], "VERSION_CONFLICT")

    def test_integer_unit_rejects_fractional_patch(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyUnit, self.unit_id).allows_fraction = False
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        line = calculated["groups"][0]["lines"][0]
        response = self.client.patch(
            f"/supply/requests/{self.request_id}/stock-calculation/lines/{line['id']}",
            json={
                "calculation_id": calculated["id"],
                "expected_revision": calculated["revision"],
                "expected_version": calculated["version"],
                "expected_line_version": line["version"],
                "quantity": "1.500",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "SUPPLY_STOCK_TRANSFER_FRACTION_NOT_ALLOWED",
        )

    def test_manual_transferable_cannot_exceed_source_balance(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplyRequestLine, self.line_id).quantity = Decimal("10")
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        calculation = calculated.json()
        line = calculation["groups"][0]["lines"][0]
        response = self.client.patch(
            f"/supply/requests/{self.request_id}/stock-calculation/lines/{line['id']}",
            json={
                "calculation_id": calculation["id"],
                "expected_revision": calculation["revision"],
                "expected_version": calculation["version"],
                "expected_line_version": line["version"],
                "quantity": "9.000",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "SUPPLY_STOCK_TRANSFER_EXCEEDS_AVAILABLE",
        )

    def test_manual_transferable_cannot_exceed_requested_line_quantity(self) -> None:
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        line = calculated["groups"][0]["lines"][0]
        response = self.client.patch(
            f"/supply/requests/{self.request_id}/stock-calculation/lines/{line['id']}",
            json={
                "calculation_id": calculated["id"],
                "expected_revision": calculated["revision"],
                "expected_version": calculated["version"],
                "expected_line_version": line["version"],
                "quantity": "6.000",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "SUPPLY_STOCK_TRANSFER_EXCEEDS_AVAILABLE",
        )

    def test_calculation_blocks_missing_source(self) -> None:
        with self.sessions.begin() as session:
            mapping = session.scalar(select(SupplyProductSourceMapping))
            session.delete(mapping)
        without_source = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(without_source.status_code, 200, without_source.text)
        blocked = without_source.json()["groups"][0]["lines"][0]
        self.assertIn("SOURCE", blocked["unavailable_reason"])

    def test_blocked_calculation_cannot_be_confirmed(self) -> None:
        with self.sessions.begin() as session:
            session.delete(session.scalar(select(SupplyProductSourceMapping)))
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": calculated["id"],
                "expected_revision": calculated["revision"],
                "expected_version": calculated["version"],
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "SUPPLY_STOCK_CALCULATION_BLOCKED",
        )

    def test_stale_confirm_after_recalculation_returns_version_conflict(self) -> None:
        stale = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        current = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        ).json()
        response = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": stale["id"],
                "expected_revision": stale["revision"],
                "expected_version": stale["version"],
            },
        )
        self.assertEqual(current["revision"], stale["revision"] + 1)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "VERSION_CONFLICT")

    def test_tied_sync_timestamps_use_highest_run_id(self) -> None:
        timestamp = self.initial_sync_at + timedelta(hours=2)
        self._add_stock_sync(
            "2.000",
            timestamp,
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
            started_at=timestamp,
        )
        self._add_stock_sync(
            "7.000",
            timestamp,
            run_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            started_at=timestamp,
        )
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        self.assertEqual(calculated.status_code, 200, calculated.text)
        line = calculated.json()["groups"][0]["lines"][0]
        self.assertEqual(Decimal(line["available_quantity"]), Decimal("7"))

    def test_confirmed_calculation_does_not_change_after_new_sync(self) -> None:
        calculated = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/calculate"
        )
        original = calculated.json()["groups"][0]["lines"][0]
        confirmed = self.client.post(
            f"/supply/requests/{self.request_id}/stock-calculation/confirm",
            json={
                "calculation_id": calculated.json()["id"],
                "expected_revision": calculated.json()["revision"],
                "expected_version": calculated.json()["version"],
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self._add_stock_sync(
            "1.000", self.initial_sync_at + timedelta(hours=1)
        )
        current = self.client.get(
            f"/supply/requests/{self.request_id}/stock-calculation"
        )
        self.assertEqual(current.status_code, 200, current.text)
        current_line = current.json()["groups"][0]["lines"][0]
        self.assertEqual(current.json()["status"], "CONFIRMED")
        self.assertEqual(
            Decimal(current_line["available_quantity"]),
            Decimal(original["available_quantity"]),
        )
        self.assertEqual(
            current_line["transferable_quantity"],
            original["transferable_quantity"],
        )


if __name__ == "__main__":
    unittest.main()
