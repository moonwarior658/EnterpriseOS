import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.supply import (
    Department,
    SupplyProduct,
    SupplyProductSupplier,
    SupplyPurchaseAllocation,
    SupplySupplierOrder,
    SupplySupplierOrderLine,
    SupplyProductCategory,
    SupplyPurchaseRequest,
    SupplyPurchaseRequestLine,
    SupplyPurchaseRequestLineSource,
    SupplyProcurementNeed,
    SupplyDepartmentDebt,
    SupplyUnit,
    SupplyRequestDirection,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestLine,
    SupplyStockCalculation,
    SupplyStockCalculationLine,
    SupplyStorageZone,
    SupplySupplier,
)
from app.models.user import User
from app.models.iiko import IikoWarehouseMapping
from app.models.work_request import WorkRequest


class SupplyPurchaseRequestsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine, "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        for table in (
            User.__table__, WorkRequest.__table__, SupplyUnit.__table__, SupplyRequestDirection.__table__,
            Department.__table__, IikoWarehouseMapping.__table__, SupplyRequestCycle.__table__,
            SupplyProductCategory.__table__, SupplyStorageZone.__table__,
            SupplyProduct.__table__,
            SupplySupplier.__table__, SupplyProductSupplier.__table__,
            SupplyRequest.__table__, SupplyRequestLine.__table__,
            SupplyStockCalculation.__table__, SupplyStockCalculationLine.__table__,
            SupplyDepartmentDebt.__table__,
            SupplyPurchaseRequest.__table__, SupplyPurchaseRequestLine.__table__,
            SupplyProcurementNeed.__table__,
            SupplyPurchaseRequestLineSource.__table__,
            SupplyPurchaseAllocation.__table__,
            SupplySupplierOrder.__table__, SupplySupplierOrderLine.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            session.add_all([
                User(id=1, username="employee", display_name="Employee", hashed_password="x", tenant_id="eclair", is_active=True, is_admin=False),
                User(id=2, username="admin", display_name="Admin", hashed_password="x", tenant_id="eclair", is_active=True, is_admin=True),
                User(id=3, username="other", display_name="Other", hashed_password="x", tenant_id="other", is_active=True, is_admin=True),
            ])
            self.unit = SupplyUnit(tenant_id="eclair", code="KG", name_ru="Килограмм", short_name_ru="кг", allows_fraction=True, is_active=True)
            self.unit_two = SupplyUnit(tenant_id="eclair", code="BOX", name_ru="Коробка", short_name_ru="кор.", allows_fraction=False, is_active=True)
            self.other_unit = SupplyUnit(tenant_id="other", code="KG", name_ru="Килограмм", short_name_ru="кг", allows_fraction=True, is_active=True)
            session.add_all([self.unit, self.unit_two, self.other_unit])
            session.flush()
            self.product = SupplyProduct(tenant_id="eclair", name="Сахар", normalized_name="сахар", default_unit_id=self.unit.id, is_active=True)
            self.other_product = SupplyProduct(tenant_id="other", name="Сахар", normalized_name="сахар", default_unit_id=self.other_unit.id, is_active=True)
            session.add_all([self.product, self.other_product])
            session.flush()
            self.supplier = SupplySupplier(
                tenant_id="eclair", display_name="Основной поставщик", is_active=True
            )
            self.backup_supplier = SupplySupplier(
                tenant_id="eclair", display_name="Резервный поставщик", is_active=True
            )
            self.other_supplier = SupplySupplier(
                tenant_id="other", display_name="Чужой поставщик", is_active=True
            )
            session.add_all([self.supplier, self.backup_supplier, self.other_supplier])
            session.flush()
            self.primary_relation = SupplyProductSupplier(
                tenant_id="eclair", product_id=self.product.id,
                supplier_id=self.supplier.id, role="PRIMARY", priority=10,
                package_quantity=Decimal("12.000"), package_unit_id=self.unit.id,
                price_per_package=Decimal("4956.00"), currency="RUB",
                is_available=True, is_active=True,
            )
            self.backup_relation = SupplyProductSupplier(
                tenant_id="eclair", product_id=self.product.id,
                supplier_id=self.backup_supplier.id, role="BACKUP", priority=20,
                package_quantity=Decimal("12.000"), package_unit_id=self.unit.id,
                price_per_package=Decimal("5280.00"), currency="RUB",
                is_available=True, is_active=True,
            )
            self.other_relation = SupplyProductSupplier(
                tenant_id="other", product_id=self.other_product.id,
                supplier_id=self.other_supplier.id, role="PRIMARY", priority=10,
                package_quantity=Decimal("10.000"), package_unit_id=self.other_unit.id,
                price_per_package=Decimal("100.00"), currency="RUB",
                is_available=True, is_active=True,
            )
            session.add_all([self.primary_relation, self.backup_relation, self.other_relation])
            self.department = Department(tenant_id="eclair", code="M15", name="М15", is_active=True, display_order=1)
            self.direction = SupplyRequestDirection(tenant_id="eclair", code="FOOD", name="Продукты", is_active=True, display_order=1)
            session.add_all([self.department, self.direction])
        self.current_user_id = 2

        def override_db():
            with self.sessions() as session:
                yield session

        def override_user():
            with self.sessions() as session:
                return session.get(User, self.current_user_id)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine.dispose()

    def create_request(self):
        response = self.client.post("/supply/purchase-requests", json={
            "need_date": (date.today() + timedelta(days=1)).isoformat(),
            "comment": " Закупка к выпуску ",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def add_line(self, request_id, **changes):
        payload = {
            "product_id": str(self.product.id), "quantity": "80.000",
            "unit_id": str(self.unit.id), "comment": " Основная потребность ",
        }
        payload.update(changes)
        return self.client.post(
            f"/supply/purchase-requests/{request_id}/lines", json=payload
        )

    def add_need(self, quantity="10.000", *, unit=None, need_date=None, status="OPEN", null_date=False):
        unit = unit or self.unit
        suffix = uuid4().hex[:8]
        with self.sessions.begin() as session:
            request = SupplyRequest(
                tenant_id="eclair", public_number=f"REQ-{suffix}",
                department_id=self.department.id, direction_id=self.direction.id,
                need_date=None if null_date else need_date if need_date is not None else date.today(),
                status="PLANNED", source_type="INTERNAL", raw_input="Сахар",
            )
            session.add(request); session.flush()
            line = SupplyRequestLine(
                tenant_id="eclair", request_id=request.id, position=1,
                raw_text="Сахар", product_id=self.product.id,
                requested_unit_id=unit.id, quantity=Decimal(quantity),
                match_status="MATCHED",
            )
            session.add(line); session.flush()
            calculation = SupplyStockCalculation(
                tenant_id="eclair", request_id=request.id, revision=1,
                version=1, status="PRELIMINARY",
                calculated_at=datetime.now(timezone.utc),
            )
            session.add(calculation); session.flush()
            calculation_line = SupplyStockCalculationLine(
                tenant_id="eclair", calculation_id=calculation.id,
                request_id=request.id, request_line_id=line.id, version=1,
                position=1, product_id=self.product.id, product_name="Сахар",
                requested_unit_id=unit.id, requested_quantity=Decimal(quantity),
                available_quantity=Decimal("0"), transferable_quantity=Decimal("0"),
                deficit_quantity=Decimal(quantity),
            )
            session.add(calculation_line); session.flush()
            need = SupplyProcurementNeed(
                tenant_id="eclair", source_type="REQUEST_LINE",
                supply_request_line_id=line.id,
                basis_stock_calculation_line_id=calculation_line.id,
                product_id=self.product.id, unit_id=unit.id,
                quantity=Decimal(quantity),
                need_date=None if null_date else need_date if need_date is not None else date.today(),
                status=status, reason="INTERNAL_STOCK_DEFICIT", version=1,
                closed_at=datetime.now(timezone.utc) if status in {"CLOSED", "CANCELLED"} else None,
            )
            session.add(need); session.flush()
            return need.id

    def test_create_list_get_update_and_number(self) -> None:
        created = self.create_request()
        self.assertRegex(created["number"], r"^ZR-\d{8}-001$")
        self.assertEqual(created["status"], "DRAFT")
        self.assertEqual(created["comment"], "Закупка к выпуску")
        self.assertEqual(created["lines"], [])
        listed = self.client.get("/supply/purchase-requests")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["line_count"], 0)
        updated = self.client.patch(
            f"/supply/purchase-requests/{created['id']}",
            json={"comment": "Уточнено"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["comment"], "Уточнено")
        self.assertEqual(
            self.client.get(f"/supply/purchase-requests/{created['id']}").status_code,
            200,
        )

    def test_line_crud_sources_and_uniqueness(self) -> None:
        request_id = self.create_request()["id"]
        added = self.add_line(request_id)
        self.assertEqual(added.status_code, 201, added.text)
        line = added.json()["lines"][0]
        self.assertEqual(line["product"]["name"], "Сахар")
        self.assertEqual(line["sources"][0]["source_type"], "MANUAL_FUTURE")
        self.assertEqual(line["sources"][0]["quantity"], "80.000")
        self.assertEqual(line["sources"][0]["unit"]["short_name_ru"], "кг")
        self.assertEqual(self.add_line(request_id).status_code, 409)
        different_unit = self.add_line(request_id, unit_id=str(self.unit_two.id))
        self.assertEqual(different_unit.status_code, 201, different_unit.text)
        updated = self.client.patch(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}",
            json={"quantity": "90.000", "comment": "Исправлено"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        updated_line = next(
            item for item in updated.json()["lines"] if item["id"] == line["id"]
        )
        self.assertEqual(updated_line["sources"][0]["quantity"], "90.000")
        deleted = self.client.delete(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}"
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(len(deleted.json()["lines"]), 1)

    def test_ready_and_cancelled_are_read_only(self) -> None:
        request_id = self.create_request()["id"]
        self.assertEqual(self.add_line(request_id).status_code, 201)
        ready = self.client.post(f"/supply/purchase-requests/{request_id}/ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(ready.json()["status"], "READY")
        line_id = ready.json()["lines"][0]["id"]
        self.assertEqual(self.add_line(request_id).status_code, 409)
        self.assertEqual(self.client.patch(f"/supply/purchase-requests/{request_id}/lines/{line_id}", json={"quantity": "1"}).status_code, 409)
        self.assertEqual(self.client.delete(f"/supply/purchase-requests/{request_id}/lines/{line_id}").status_code, 409)
        cancelled = self.client.post(f"/supply/purchase-requests/{request_id}/cancel")
        self.assertEqual(cancelled.status_code, 409, cancelled.text)
        self.assertEqual(self.client.patch(f"/supply/purchase-requests/{request_id}", json={"comment": "x"}).status_code, 409)
        self.assertEqual(self.client.post(f"/supply/purchase-requests/{request_id}/cancel").status_code, 409)

    def test_allocation_workspace_split_coverage_snapshot_and_confirmation(self) -> None:
        request_id = self.create_request()["id"]
        added = self.add_line(request_id, quantity="120.000")
        line_id = added.json()["lines"][0]["id"]
        self.assertEqual(self.client.get(f"/supply/purchase-requests/{request_id}/allocations").status_code, 409)
        self.assertEqual(self.client.post(f"/supply/purchase-requests/{request_id}/ready").status_code, 200)

        first = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations",
            json={"product_supplier_id": str(self.primary_relation.id), "packages_count": 6},
        )
        self.assertEqual(first.status_code, 201, first.text)
        line = first.json()["lines"][0]
        self.assertEqual(line["allocated_quantity"], "72.000000")
        self.assertEqual(line["remaining_quantity"], "48.000000")
        self.assertEqual(line["planned_amount"], "29736.000000")
        self.assertEqual([item["role"] for item in line["eligible_suppliers"]], ["PRIMARY", "BACKUP"])

        duplicate = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations",
            json={"product_supplier_id": str(self.primary_relation.id), "packages_count": 1},
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        second = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations",
            json={"product_supplier_id": str(self.backup_relation.id), "packages_count": 5},
        )
        self.assertEqual(second.status_code, 201, second.text)
        line = second.json()["lines"][0]
        self.assertEqual(line["allocated_quantity"], "132.000000")
        self.assertEqual(line["remaining_quantity"], "0")
        self.assertEqual(line["overallocated_quantity"], "12.000000")
        self.assertEqual(second.json()["planned_total_amount"], "56136.000000")
        self.assertEqual(len(second.json()["supplier_subtotals"]), 2)

        allocation = line["allocations"][0]
        with self.sessions.begin() as session:
            relation = session.get(SupplyProductSupplier, self.primary_relation.id)
            relation.price_per_package = Decimal("6000.00")
            relation.package_quantity = Decimal("15.000")
        workspace = self.client.get(f"/supply/purchase-requests/{request_id}/allocations")
        saved = workspace.json()["lines"][0]["allocations"][0]
        self.assertEqual(saved["price_per_package_snapshot"], "4956.00")
        self.assertEqual(saved["package_quantity_snapshot"], "12.000")
        self.assertTrue(saved["current_terms_changed"])

        updated_snapshot = self.client.patch(
            f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations/{allocation['id']}",
            json={"packages_count": 7},
        )
        saved = updated_snapshot.json()["lines"][0]["allocations"][0]
        self.assertEqual(saved["quantity_base"], "84.000000")
        self.assertEqual(saved["planned_amount"], "34692.000000")
        self.assertEqual(saved["price_per_package_snapshot"], "4956.00")

        confirmed = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations/{allocation['id']}/confirm"
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["lines"][0]["allocations"][0]["status"], "CONFIRMED")
        self.assertEqual(self.client.patch(
            f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations/{allocation['id']}",
            json={"packages_count": 8},
        ).status_code, 409)

    def test_allocation_rejects_ineligible_unit_availability_and_cross_tenant(self) -> None:
        request_id = self.create_request()["id"]
        added = self.add_line(request_id, quantity="25.000")
        line_id = added.json()["lines"][0]["id"]
        self.client.post(f"/supply/purchase-requests/{request_id}/ready")
        endpoint = f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations"
        self.assertEqual(self.client.post(endpoint, json={
            "product_supplier_id": str(self.other_relation.id), "packages_count": 1,
        }).status_code, 409)
        with self.sessions.begin() as session:
            relation = session.get(SupplyProductSupplier, self.primary_relation.id)
            relation.package_unit_id = self.unit_two.id
        self.assertEqual(self.client.post(endpoint, json={
            "product_supplier_id": str(self.primary_relation.id), "packages_count": 1,
        }).status_code, 409)

        with self.sessions.begin() as session:
            relation = session.get(SupplyProductSupplier, self.primary_relation.id)
            relation.package_unit_id = self.unit.id
            relation.is_available = True
            relation.price_per_package = None
        self.assertEqual(self.client.post(endpoint, json={
            "product_supplier_id": str(self.primary_relation.id), "packages_count": 1,
        }).status_code, 409)
        with self.sessions.begin() as session:
            relation = session.get(SupplyProductSupplier, self.primary_relation.id)
            relation.price_per_package = Decimal("4956.00")
            relation.is_active = False
            relation.archived_at = datetime.now(timezone.utc)
            relation.archived_by_user_id = 2
        self.assertEqual(self.client.post(endpoint, json={
            "product_supplier_id": str(self.primary_relation.id), "packages_count": 1,
        }).status_code, 409)
        with self.sessions.begin() as session:
            relation = session.get(SupplyProductSupplier, self.primary_relation.id)
            relation.is_active = True
            relation.archived_at = None
            relation.archived_by_user_id = None
            supplier = session.get(SupplySupplier, self.supplier.id)
            supplier.is_active = False
            supplier.archived_at = datetime.now(timezone.utc)
            supplier.archived_by_user_id = 2
        self.assertEqual(self.client.post(endpoint, json={
            "product_supplier_id": str(self.primary_relation.id), "packages_count": 1,
        }).status_code, 409)
        with self.sessions.begin() as session:
            supplier = session.get(SupplySupplier, self.supplier.id)
            supplier.is_active = True
            supplier.archived_at = None
            supplier.archived_by_user_id = None
            second_product = SupplyProduct(
                tenant_id="eclair", name="Мука", normalized_name="мука",
                default_unit_id=self.unit.id, is_active=True,
            )
            session.add(second_product); session.flush()
            wrong_product_relation = SupplyProductSupplier(
                tenant_id="eclair", product_id=second_product.id,
                supplier_id=self.supplier.id, role="PRIMARY", priority=10,
                package_quantity=Decimal("10.000"), package_unit_id=self.unit.id,
                price_per_package=Decimal("1000.00"), currency="RUB",
                is_available=True, is_active=True,
            )
            session.add(wrong_product_relation); session.flush()
            wrong_product_relation_id = wrong_product_relation.id
        self.assertEqual(self.client.post(endpoint, json={
            "product_supplier_id": str(wrong_product_relation_id), "packages_count": 1,
        }).status_code, 409)

        cancelled_id = self.create_request()["id"]
        cancelled_line = self.add_line(cancelled_id).json()["lines"][0]["id"]
        self.assertEqual(self.client.post(f"/supply/purchase-requests/{cancelled_id}/cancel").status_code, 200)
        self.assertEqual(self.client.post(
            f"/supply/purchase-requests/{cancelled_id}/lines/{cancelled_line}/allocations",
            json={"product_supplier_id": str(self.primary_relation.id), "packages_count": 1},
        ).status_code, 409)
        with self.sessions.begin() as session:
            relation = session.get(SupplyProductSupplier, self.primary_relation.id)
            relation.package_unit_id = self.unit.id
            relation.is_available = False
        self.assertEqual(self.client.post(endpoint, json={
            "product_supplier_id": str(self.primary_relation.id), "packages_count": 1,
        }).status_code, 409)

    def test_supplier_minimum_order_aggregates_all_lines_and_statuses(self) -> None:
        with self.sessions.begin() as session:
            session.get(
                SupplySupplier, self.supplier.id
            ).minimum_order_amount = Decimal("32000.00")
            second_product = SupplyProduct(
                tenant_id="eclair", name="Мука", normalized_name="мука",
                default_unit_id=self.unit.id, is_active=True,
            )
            session.add(second_product)
            session.flush()
            second_relation = SupplyProductSupplier(
                tenant_id="eclair", product_id=second_product.id,
                supplier_id=self.supplier.id, role="PRIMARY", priority=10,
                package_quantity=Decimal("10.000"), package_unit_id=self.unit.id,
                price_per_package=Decimal("1000.00"), currency="RUB",
                is_available=True, is_active=True,
            )
            session.add(second_relation)
            session.flush()
            second_product_id = second_product.id
            second_relation_id = second_relation.id

        request_id = self.create_request()["id"]
        first_line_id = self.add_line(
            request_id, quantity="100.000"
        ).json()["lines"][0]["id"]
        second_line_response = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines",
            json={
                "product_id": str(second_product_id), "quantity": "20.000",
                "unit_id": str(self.unit.id), "comment": None,
            },
        )
        self.assertEqual(
            second_line_response.status_code, 201, second_line_response.text
        )
        second_line_id = next(
            line["id"] for line in second_line_response.json()["lines"]
            if line["product_id"] == str(second_product_id)
        )
        self.client.post(f"/supply/purchase-requests/{request_id}/ready")

        first = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{first_line_id}/allocations",
            json={
                "product_supplier_id": str(self.primary_relation.id),
                "packages_count": 6,
            },
        )
        first_allocation_id = next(
            line for line in first.json()["lines"]
            if line["line_id"] == first_line_id
        )["allocations"][0]["id"]
        second = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{second_line_id}/allocations",
            json={
                "product_supplier_id": str(second_relation_id),
                "packages_count": 2,
            },
        )
        self.assertEqual(second.status_code, 201, second.text)
        no_minimum = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{first_line_id}/allocations",
            json={
                "product_supplier_id": str(self.backup_relation.id),
                "packages_count": 1,
            },
        )
        self.assertEqual(no_minimum.status_code, 201, no_minimum.text)

        subtotals = {
            item["supplier_id"]: item
            for item in no_minimum.json()["supplier_subtotals"]
        }
        primary = subtotals[str(self.supplier.id)]
        self.assertEqual(primary["planned_total_amount"], "31736.000000")
        self.assertEqual(primary["minimum_order_amount"], "32000.00")
        self.assertEqual(primary["minimum_order_status"], "BELOW_MINIMUM")
        self.assertEqual(primary["minimum_order_shortfall"], "264.000000")
        self.assertEqual(primary["allocation_count"], 2)
        backup = subtotals[str(self.backup_supplier.id)]
        self.assertEqual(backup["minimum_order_status"], "NOT_CONFIGURED")
        self.assertEqual(backup["minimum_order_shortfall"], "0")

        confirmed = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{first_line_id}/allocations/"
            f"{first_allocation_id}/confirm"
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        primary = next(
            item for item in confirmed.json()["supplier_subtotals"]
            if item["supplier_id"] == str(self.supplier.id)
        )
        self.assertEqual(primary["planned_total_amount"], "31736.000000")

        for minimum, expected_status in (
            ("31736.00", "MET"),
            ("30000.00", "MET"),
        ):
            with self.sessions.begin() as session:
                session.get(
                    SupplySupplier, self.supplier.id
                ).minimum_order_amount = Decimal(minimum)
            workspace = self.client.get(
                f"/supply/purchase-requests/{request_id}/allocations"
            )
            primary = next(
                item for item in workspace.json()["supplier_subtotals"]
                if item["supplier_id"] == str(self.supplier.id)
            )
            self.assertEqual(primary["minimum_order_status"], expected_status)
            self.assertEqual(primary["minimum_order_shortfall"], "0")

    def test_supplier_orders_group_snapshot_idempotency_ready_cancel_and_release(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplySupplier, self.supplier.id).minimum_order_amount = Decimal("40000.00")
        request_id = self.create_request()["id"]
        line_id = self.add_line(request_id, quantity="120.000").json()["lines"][0]["id"]
        self.client.post(f"/supply/purchase-requests/{request_id}/ready")
        allocation_ids = []
        for relation, count in ((self.primary_relation, 6), (self.backup_relation, 5)):
            workspace = self.client.post(
                f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations",
                json={"product_supplier_id": str(relation.id), "packages_count": count},
            ).json()
            allocation = next(item for item in workspace["lines"][0]["allocations"] if item["product_supplier_id"] == str(relation.id))
            allocation_ids.append(allocation["id"])
            if len(allocation_ids) == 1:
                ignored = self.client.post(
                    f"/supply/purchase-requests/{request_id}/supplier-orders"
                )
                self.assertEqual(ignored.status_code, 201, ignored.text)
                self.assertEqual(ignored.json()["orders"], [])
            response = self.client.post(
                f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations/{allocation['id']}/confirm"
            )
            self.assertEqual(response.status_code, 200, response.text)

        created = self.client.post(f"/supply/purchase-requests/{request_id}/supplier-orders")
        self.assertEqual(created.status_code, 201, created.text)
        orders = created.json()["orders"]
        self.assertEqual(len(orders), 2)
        self.assertEqual({order["supplier_display_name"] for order in orders}, {"Основной поставщик", "Резервный поставщик"})
        primary = next(order for order in orders if order["supplier_id"] == str(self.supplier.id))
        self.assertEqual(primary["status"], "DRAFT")
        self.assertEqual(primary["total_amount"], "29736.000000")
        self.assertEqual(primary["minimum_order_status"], "BELOW_MINIMUM")
        self.assertEqual(primary["minimum_order_shortfall"], "10264.000000")
        self.assertEqual(primary["lines"][0]["product_name"], "Сахар")
        self.assertEqual(primary["lines"][0]["package_quantity_snapshot"], "12.000")
        self.assertEqual(primary["lines"][0]["price_per_package_snapshot"], "4956.00")

        repeated = self.client.post(f"/supply/purchase-requests/{request_id}/supplier-orders")
        self.assertEqual({item["id"] for item in repeated.json()["orders"]}, {item["id"] for item in orders})
        order_id = primary["id"]
        patched = self.client.patch(f"/supply/supplier-orders/{order_id}", json={
            "planned_delivery_date": (date.today() + timedelta(days=2)).isoformat(),
            "comment": " После 14:00 ",
        })
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["comment"], "После 14:00")
        ready = self.client.post(f"/supply/supplier-orders/{order_id}/ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(ready.json()["status"], "READY")
        self.assertEqual(self.client.patch(f"/supply/supplier-orders/{order_id}", json={"comment": "x"}).status_code, 409)
        self.assertEqual(self.client.post(f"/supply/supplier-orders/{order_id}/cancel").status_code, 409)

        draft = next(order for order in orders if order["id"] != order_id)
        cancelled = self.client.post(f"/supply/supplier-orders/{draft['id']}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        recreated = self.client.post(f"/supply/purchase-requests/{request_id}/supplier-orders")
        self.assertEqual(len(recreated.json()["orders"]), 1)
        self.assertNotEqual(recreated.json()["orders"][0]["id"], draft["id"])

        with self.sessions.begin() as session:
            relation = session.get(SupplyProductSupplier, self.backup_relation.id)
            relation.price_per_package = Decimal("9999.00")
        detail = self.client.get(f"/supply/supplier-orders/{recreated.json()['orders'][0]['id']}")
        self.assertEqual(detail.json()["lines"][0]["price_per_package_snapshot"], "5280.00")

        listed = self.client.get("/supply/supplier-orders", params={"status": "READY", "search": primary["number"]})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)
        self.current_user_id = 3
        self.assertEqual(self.client.get(f"/supply/supplier-orders/{order_id}").status_code, 404)

    def test_collect_aggregates_is_idempotent_and_preserves_manual(self) -> None:
        request_id = self.create_request()["id"]
        self.assertEqual(self.add_line(request_id, quantity="20.000").status_code, 201)
        first_need = self.add_need("30.000")
        second_need = self.add_need("40.000")
        response = self.client.post(f"/supply/purchase-requests/{request_id}/collect-needs")
        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["lines"][0]
        self.assertEqual(line["quantity"], "90.000")
        self.assertEqual(line["manual_future_quantity"], "20.000")
        self.assertEqual(len(line["sources"]), 3)
        auto = [source for source in line["sources"] if source["source_type"] == "PROCUREMENT_NEED"]
        self.assertEqual({source["procurement_need_id"] for source in auto}, {str(first_need), str(second_need)})
        self.assertEqual(auto[0]["procurement_need"]["department"], "М15")
        repeated = self.client.post(f"/supply/purchase-requests/{request_id}/collect-needs")
        self.assertEqual(repeated.json()["lines"][0]["quantity"], "90.000")
        self.assertEqual(len(repeated.json()["lines"][0]["sources"]), 3)
        edited = self.client.patch(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}",
            json={"manual_future_quantity": "25.000"},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["lines"][0]["quantity"], "95.000")
        deleted = self.client.delete(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}"
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["lines"][0]["quantity"], "70.000")
        self.assertEqual(deleted.json()["lines"][0]["manual_future_quantity"], "0.000")

    def test_collect_filters_and_keeps_units_separate(self) -> None:
        request_id = self.create_request()["id"]
        self.add_need("5.000", need_date=date.today() + timedelta(days=10))
        self.add_need("6.000", null_date=True)
        self.add_need("7.000", status="CLOSED")
        eligible = self.add_need("8.000", unit=self.unit_two)
        response = self.client.post(f"/supply/purchase-requests/{request_id}/collect-needs")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["lines"]), 1)
        self.assertEqual(response.json()["lines"][0]["unit_id"], str(self.unit_two.id))
        with self.sessions() as session:
            self.assertEqual(str(session.get(SupplyProcurementNeed, eligible).reserved_purchase_request_id), request_id)

    def test_reconcile_updates_removes_and_releases_reservation(self) -> None:
        request_id = self.create_request()["id"]
        need_id = self.add_need("10.000")
        self.client.post(f"/supply/purchase-requests/{request_id}/collect-needs")
        with self.sessions.begin() as session:
            need = session.get(SupplyProcurementNeed, need_id)
            need.quantity = Decimal("12")
            need.version += 1
        refreshed = self.client.post(f"/supply/purchase-requests/{request_id}/collect-needs")
        self.assertEqual(refreshed.json()["lines"][0]["quantity"], "12.000")
        with self.sessions.begin() as session:
            need = session.get(SupplyProcurementNeed, need_id)
            need.status = "CLOSED"; need.closed_at = datetime.now(timezone.utc)
        empty = self.client.post(f"/supply/purchase-requests/{request_id}/collect-needs")
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json()["lines"], [])
        with self.sessions() as session:
            self.assertIsNone(session.get(SupplyProcurementNeed, need_id).reserved_purchase_request_id)

    def test_ready_validates_snapshot_and_cancel_releases_draft(self) -> None:
        stale_request = self.create_request()["id"]
        stale_need = self.add_need("10.000")
        self.client.post(f"/supply/purchase-requests/{stale_request}/collect-needs")
        with self.sessions.begin() as session:
            session.get(SupplyProcurementNeed, stale_need).quantity = Decimal("11")
        self.assertEqual(self.client.post(f"/supply/purchase-requests/{stale_request}/ready").status_code, 409)
        with self.sessions() as session:
            self.assertEqual(session.get(SupplyPurchaseRequest, UUID(stale_request)).status, "DRAFT")
            self.assertEqual(session.get(SupplyProcurementNeed, stale_need).status.value, "OPEN")

        valid_request = self.create_request()["id"]
        valid_need = self.add_need("9.000")
        self.client.post(f"/supply/purchase-requests/{valid_request}/collect-needs")
        ready = self.client.post(f"/supply/purchase-requests/{valid_request}/ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        with self.sessions() as session:
            self.assertEqual(session.get(SupplyProcurementNeed, valid_need).status.value, "IN_PURCHASE_REQUEST")

        draft_request = self.create_request()["id"]
        draft_need = self.add_need("4.000")
        self.client.post(f"/supply/purchase-requests/{draft_request}/collect-needs")
        self.assertEqual(self.client.post(f"/supply/purchase-requests/{draft_request}/cancel").status_code, 200)
        with self.sessions() as session:
            need = session.get(SupplyProcurementNeed, draft_need)
            self.assertEqual(need.status.value, "OPEN")
            self.assertIsNone(need.reserved_purchase_request_id)

    def test_need_reserved_by_another_request_is_not_double_collected(self) -> None:
        first_request = self.create_request()["id"]
        second_request = self.create_request()["id"]
        need_id = self.add_need("13.000")
        first = self.client.post(f"/supply/purchase-requests/{first_request}/collect-needs")
        second = self.client.post(f"/supply/purchase-requests/{second_request}/collect-needs")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["lines"], [])
        with self.sessions() as session:
            self.assertEqual(
                str(session.get(SupplyProcurementNeed, need_id).reserved_purchase_request_id),
                first_request,
            )

    def test_validation_and_tenant_isolation(self) -> None:
        request_id = self.create_request()["id"]
        self.assertEqual(self.add_line(request_id, quantity="0").status_code, 422)
        self.assertEqual(self.add_line(request_id, product_id=str(self.other_product.id)).status_code, 404)
        self.assertEqual(self.add_line(request_id, unit_id=str(self.other_unit.id)).status_code, 404)
        self.current_user_id = 3
        self.assertEqual(self.client.get(f"/supply/purchase-requests/{request_id}").status_code, 404)
        self.assertEqual(self.client.get("/supply/purchase-requests").json()["items"], [])

    def test_admin_only_and_empty_ready(self) -> None:
        request_id = self.create_request()["id"]
        self.assertEqual(self.client.post(f"/supply/purchase-requests/{request_id}/ready").status_code, 409)
        self.current_user_id = 1
        for method, url, body in (
            ("get", "/supply/purchase-requests", None),
            ("post", "/supply/purchase-requests", {"need_date": date.today().isoformat()}),
            ("get", f"/supply/purchase-requests/{uuid4()}", None),
        ):
            self.assertEqual(self.client.request(method, url, json=body).status_code, 403)


if __name__ == "__main__":
    unittest.main()
