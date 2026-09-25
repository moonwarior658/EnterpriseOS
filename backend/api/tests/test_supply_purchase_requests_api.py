import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pydantic import SecretStr

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.supply import (
    Department,
    SupplyProduct,
    SupplyProductSupplier,
    SupplyPurchaseAllocation,
    SupplyPurchaseAllocationSource,
    SupplySupplierOrder,
    SupplySupplierOrderDeliveryAttempt,
    SupplySupplierOrderLine,
    SupplySupplierOrderLineSource,
    SupplySupplierConfirmation,
    SupplySupplierConfirmationDeviation,
    SupplySupplierDocument,
    SupplySupplierDocumentAttachment,
    SupplySupplierDocumentLine,
    SupplySupplierObligation,
    SupplySupplierPayment,
    SupplySupplierPaymentAllocation,
    SupplySupplierSettlementAdjustment,
    SupplySupplierAcceptance,
    SupplySupplierAcceptanceLine,
    SupplySupplierAcceptanceLineSource,
    SupplyIikoIncomingReceipt,
    SupplyIikoIncomingReceiptLine,
    SupplyAcceptanceResolution,
    SupplySupplierConfirmationLine,
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
from app.models.automation import AutomationExecution, OutboxEvent
from app.automation.outbox import SqlAlchemyOutboxStore
from app.automation.providers.base import CommandAcceptance
from app.supply.supplier_order_delivery import finalize_supplier_order_email
from app.supply.supplier_order_delivery import queue_supplier_order_email
from app.supply.supplier_acceptances import _generate_resolution_issues
from app.core.config import settings
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
            SupplyPurchaseAllocationSource.__table__,
            SupplySupplierOrder.__table__, SupplySupplierOrderLine.__table__,
            SupplySupplierOrderLineSource.__table__,
            SupplySupplierConfirmation.__table__, SupplySupplierConfirmationLine.__table__,
            SupplySupplierConfirmationDeviation.__table__,
            SupplySupplierObligation.__table__,
            SupplySupplierDocument.__table__, SupplySupplierDocumentAttachment.__table__,
            SupplySupplierDocumentLine.__table__,
            SupplySupplierPayment.__table__,
            SupplySupplierPaymentAllocation.__table__,
            SupplySupplierSettlementAdjustment.__table__,
            SupplySupplierAcceptance.__table__, SupplySupplierAcceptanceLine.__table__,
            SupplySupplierAcceptanceLineSource.__table__,
            SupplyAcceptanceResolution.__table__,
            SupplyIikoIncomingReceipt.__table__,
            SupplyIikoIncomingReceiptLine.__table__,
        ):
            table.create(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("""
                CREATE TABLE automation_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, execution_id CHAR(32) UNIQUE NOT NULL,
                    schedule_id INTEGER, contract_version VARCHAR(20) NOT NULL,
                    automation_type VARCHAR(100) NOT NULL, tenant_id VARCHAR(64) NOT NULL,
                    scope_type VARCHAR(32) NOT NULL, scope_id VARCHAR(64), recipients JSON NOT NULL,
                    provider VARCHAR(64), status VARCHAR(32) NOT NULL, requested_at DATETIME NOT NULL,
                    started_at DATETIME, finished_at DATETIME, payload JSON NOT NULL, result JSON,
                    error_code VARCHAR(100), error_message TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3, next_retry_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.exec_driver_sql("""
                CREATE TABLE outbox_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_id CHAR(32) UNIQUE NOT NULL,
                    execution_id CHAR(32) NOT NULL, event_type VARCHAR(100) NOT NULL,
                    contract_version VARCHAR(20) NOT NULL, payload JSON NOT NULL,
                    status VARCHAR(32) NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 10,
                    available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    next_attempt_at DATETIME, locked_at DATETIME, locked_by VARCHAR(128),
                    published_at DATETIME, last_error TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(execution_id) REFERENCES automation_executions(execution_id)
                )
            """)
        SupplySupplierOrderDeliveryAttempt.__table__.create(self.engine)
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
                tenant_id="eclair", display_name="Основной поставщик",
                order_email="orders@example.test", is_active=True
            )
            self.backup_supplier = SupplySupplier(
                tenant_id="eclair", display_name="Резервный поставщик",
                order_email="backup@example.test", is_active=True
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
            session.flush()
            self.destination_mapping = IikoWarehouseMapping(
                tenant_id="eclair", iiko_warehouse_id=uuid4(),
                eos_department_id=self.department.id,
                destination_type="DESTINATION", role="MAIN",
                status="CONFIRMED", source_name="Основной склад М15",
                source_code="M15-MAIN", is_deleted=False,
            )
            session.add(self.destination_mapping)
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

    def create_supplier_order(self, *, delivery_date=None, comment=None, status="READY"):
        request_id = self.create_request()["id"]
        line_id = self.add_line(request_id, quantity="24.000").json()["lines"][0]["id"]
        self.client.post(f"/supply/purchase-requests/{request_id}/ready")
        workspace = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations",
            json={"product_supplier_id": str(self.primary_relation.id), "packages_count": 2},
        ).json()
        allocation_id = workspace["lines"][0]["allocations"][0]["id"]
        self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line_id}/allocations/{allocation_id}/confirm"
        )
        order = self.client.post(
            f"/supply/purchase-requests/{request_id}/supplier-orders"
        ).json()["orders"][0]
        if delivery_date is not None or comment is not None:
            order = self.client.patch(
                f"/supply/supplier-orders/{order['id']}",
                json={"planned_delivery_date": delivery_date, "comment": comment},
            ).json()
        if status == "READY":
            order = self.client.post(f"/supply/supplier-orders/{order['id']}/ready").json()
        elif status == "CANCELLED":
            order = self.client.post(f"/supply/supplier-orders/{order['id']}/cancel").json()
        return order

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

    def test_quantity_traceability_explicit_distribution_snapshot_acceptance_and_coverage(self) -> None:
        need_a = self.add_need("30.000", need_date=date.today() - timedelta(days=1))
        need_b = self.add_need("40.000", need_date=date.today() - timedelta(days=1))
        request_id = self.create_request()["id"]
        collected = self.client.post(
            f"/supply/purchase-requests/{request_id}/collect-needs"
        )
        self.assertEqual(collected.status_code, 200, collected.text)
        line = collected.json()["lines"][0]
        self.assertEqual(len(line["sources"]), 2)
        self.client.post(f"/supply/purchase-requests/{request_id}/ready")

        created = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}/allocations",
            json={"product_supplier_id": str(self.primary_relation.id), "packages_count": 6},
        )
        self.assertEqual(created.status_code, 201, created.text)
        allocation = created.json()["lines"][0]["allocations"][0]
        self.assertEqual(allocation["traceability_status"], "INCOMPLETE")
        blocked = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}/allocations/{allocation['id']}/confirm"
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)

        quantities = {str(need_a): "30.000", str(need_b): "40.000"}
        distributed = self.client.put(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}/allocations/{allocation['id']}/sources",
            json={"sources": [
                {
                    "purchase_request_line_source_id": source["purchase_request_line_source_id"],
                    "allocated_quantity": quantities[source["procurement_need_id"]],
                }
                for source in allocation["sources"]
            ]},
        )
        self.assertEqual(distributed.status_code, 200, distributed.text)
        allocation = distributed.json()["lines"][0]["allocations"][0]
        self.assertEqual(allocation["source_covered_quantity"], "70.000000")
        self.assertEqual(allocation["procurement_surplus_quantity"], "2.000000")
        confirmed = self.client.post(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}/allocations/{allocation['id']}/confirm"
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        order = self.client.post(
            f"/supply/purchase-requests/{request_id}/supplier-orders"
        ).json()["orders"][0]
        self.assertEqual(len(order["lines"][0]["sources"]), 2)
        self.client.post(f"/supply/supplier-orders/{order['id']}/ready")
        with self.sessions.begin() as session:
            stored = session.get(SupplySupplierOrder, UUID(order["id"]))
            stored.status = "SENT"
            stored.sent_at = datetime.now(timezone.utc)

        acceptance = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances",
            json={"destination_mapping_id": str(self.destination_mapping.id)},
        )
        self.assertEqual(acceptance.status_code, 201, acceptance.text)
        acceptance_line = acceptance.json()["lines"][0]
        updated = self.client.patch(
            f"/supply/supplier-acceptances/{acceptance.json()['id']}/lines/{acceptance_line['id']}",
            json={"received_quantity": "40", "accepted_quantity": "40", "rejected_quantity": "0"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        acceptance_line = updated.json()["lines"][0]
        self.assertEqual(acceptance_line["traceability_status"], "INCOMPLETE")
        accepted_by_need = {str(need_a): "30", str(need_b): "10"}
        accepted = self.client.put(
            f"/supply/supplier-acceptances/{acceptance.json()['id']}/lines/{acceptance_line['id']}/sources",
            json={"sources": [
                {
                    "supplier_order_line_source_id": source["supplier_order_line_source_id"],
                    "accepted_quantity": accepted_by_need[source["procurement_need_id"]],
                }
                for source in acceptance_line["sources"]
            ]},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        recorded = self.client.post(
            f"/supply/supplier-acceptances/{acceptance.json()['id']}/record"
        )
        self.assertEqual(recorded.status_code, 200, recorded.text)

        coverage = self.client.get(
            f"/supply/purchase-requests/{request_id}/coverage"
        )
        self.assertEqual(coverage.status_code, 200, coverage.text)
        by_need = {item["procurement_need_id"]: item for item in coverage.json()["needs"]}
        self.assertEqual(by_need[str(need_a)]["coverage_status"], "FULLY_COVERED")
        self.assertTrue(by_need[str(need_a)]["has_delay"])
        self.assertEqual(by_need[str(need_b)]["coverage_status"], "PARTIALLY_COVERED")
        self.assertEqual(by_need[str(need_b)]["covered_quantity"], "10.000000")

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

    def test_prepare_supplier_order_message_snapshots_and_is_idempotent(self) -> None:
        order = self.create_supplier_order(
            delivery_date="2026-09-20", comment="Внутренняя скидка требует проверки"
        )
        endpoint = f"/supply/supplier-orders/{order['id']}/prepare-message"
        missing_phone = self.client.post(endpoint, json={})
        self.assertEqual(missing_phone.status_code, 409)
        self.assertEqual(missing_phone.json()["detail"], "Укажите телефон ответственного")
        prepared = self.client.post(endpoint, json={"responsible_phone": " +7 900 000-00-00 "})
        self.assertEqual(prepared.status_code, 200, prepared.text)
        preview = prepared.json()
        self.assertEqual(preview["recipient"], {
            "email": "orders@example.test",
            "supplier_display_name": "Основной поставщик",
        })
        self.assertEqual(preview["subject"], f"Заказ {order['number']} на 20.09.2026")
        self.assertEqual(preview["order"]["comment"], None)
        self.assertNotIn("Внутренняя скидка", preview["body_text"])
        self.assertIn("Заказ сформирован автоматически в EnterpriseOS", preview["body_text"])
        self.assertEqual(preview["responsible"], {
            "name": "Admin", "phone": "+7 900 000-00-00",
        })
        self.assertEqual(preview["lines"][0]["product_name"], "Сахар")
        self.assertEqual(preview["lines"][0]["packages_count"], 2)
        self.assertEqual(preview["lines"][0]["package_quantity"], "12.000")
        self.assertEqual(preview["lines"][0]["price_per_package"], "4956.00")
        self.assertEqual(preview["lines"][0]["planned_amount"], "9912.000000")
        self.assertEqual(preview["warnings"], [])

        with self.sessions.begin() as session:
            session.get(SupplySupplier, self.supplier.id).order_email = "new@example.test"
            session.get(SupplyProductSupplier, self.primary_relation.id).price_per_package = Decimal("9999.00")
            session.get(User, 2).display_name = "Новый администратор"
        repeated = self.client.post(endpoint, json={})
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json(), preview)
        detail = self.client.get(f"/supply/supplier-orders/{order['id']}").json()
        self.assertEqual(detail["recipient_email_snapshot"], "orders@example.test")
        self.assertEqual(detail["responsible_name_snapshot"], "Admin")

    def test_prepare_message_allows_missing_date_with_warning(self) -> None:
        order = self.create_supplier_order()
        prepared = self.client.post(
            f"/supply/supplier-orders/{order['id']}/prepare-message",
            json={"responsible_phone": "+7 900 000-00-01"},
        )
        self.assertEqual(prepared.status_code, 200, prepared.text)
        self.assertEqual(prepared.json()["subject"], f"Заказ {order['number']}")
        self.assertEqual(prepared.json()["warnings"], ["Дата поставки не указана"])

    def test_prepare_message_rejects_wrong_state_missing_email_and_cross_tenant(self) -> None:
        draft = self.create_supplier_order(status="DRAFT")
        draft_endpoint = f"/supply/supplier-orders/{draft['id']}/prepare-message"
        self.assertEqual(self.client.post(draft_endpoint, json={"responsible_phone": "1"}).status_code, 409)
        cancelled = self.create_supplier_order(status="CANCELLED")
        self.assertEqual(self.client.post(
            f"/supply/supplier-orders/{cancelled['id']}/prepare-message",
            json={"responsible_phone": "1"},
        ).status_code, 409)

        ready = self.create_supplier_order()
        with self.sessions.begin() as session:
            session.get(SupplySupplier, self.supplier.id).order_email = None
        missing_email = self.client.post(
            f"/supply/supplier-orders/{ready['id']}/prepare-message",
            json={"responsible_phone": "1"},
        )
        self.assertEqual(missing_email.status_code, 409)
        self.assertEqual(missing_email.json()["detail"], "У поставщика не указан корректный email для заказов")

        with self.sessions.begin() as session:
            session.get(SupplySupplier, self.supplier.id).order_email = "orders@example.test"
        self.current_user_id = 3
        self.assertEqual(self.client.post(
            f"/supply/supplier-orders/{ready['id']}/prepare-message",
            json={"responsible_phone": "1"},
        ).status_code, 404)

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

    def test_supplier_order_email_queue_is_atomic_idempotent_and_dispatched(self) -> None:
        order = self.create_supplier_order()
        prepare = self.client.post(
            f"/supply/supplier-orders/{order['id']}/prepare-message",
            json={"responsible_phone": "+7 900 000-00-00"},
        )
        self.assertEqual(prepare.status_code, 200, prepare.text)

        endpoint = f"/supply/supplier-orders/{order['id']}/send"
        first = self.client.post(endpoint)
        second = self.client.post(endpoint)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["status"], "PENDING")

        with self.sessions() as session:
            attempts = session.scalars(select(SupplySupplierOrderDeliveryAttempt)).all()
            executions = session.scalars(select(AutomationExecution)).all()
            outbox = session.scalars(select(OutboxEvent)).all()
            self.assertEqual((len(attempts), len(executions), len(outbox)), (1, 1, 1))
            self.assertEqual(set(executions[0].payload), {
                "delivery_attempt_id", "recipient", "subject", "body_text",
            })
            self.assertEqual(executions[0].payload["recipient"], "orders@example.test")
            self.assertEqual(attempts[0].recipient_email, "orders@example.test")

        store = SqlAlchemyOutboxStore(self.sessions)
        claimed = store.claim_next(
            worker_id="email-test", claimed_at=datetime.now(timezone.utc),
        )
        self.assertIsNotNone(claimed)
        store.mark_published(
            claimed,
            acceptance=CommandAcceptance(provider="n8n", accepted=True, status_code=202),
            published_at=datetime.now(timezone.utc),
        )
        detail = self.client.get(f"/supply/supplier-orders/{order['id']}").json()
        self.assertEqual(detail["status"], "READY")
        self.assertEqual(detail["latest_delivery_attempt"]["status"], "DISPATCHED")

    def test_supplier_order_email_success_failure_retry_and_snapshot(self) -> None:
        order = self.create_supplier_order()
        self.client.post(
            f"/supply/supplier-orders/{order['id']}/prepare-message",
            json={"responsible_phone": "+7 900 000-00-00"},
        )
        first = self.client.post(f"/supply/supplier-orders/{order['id']}/send").json()
        with self.sessions.begin() as session:
            attempt = session.get(SupplySupplierOrderDeliveryAttempt, UUID(first["id"]))
            finalize_supplier_order_email(
                session, attempt.automation_execution_id, succeeded=False,
                completed_at=datetime.now(timezone.utc), error_code="SMTP_REJECTED",
                error_message="Mailbox rejected message",
            )
            session.get(SupplySupplier, self.supplier.id).order_email = "changed@example.test"

        retry = self.client.post(f"/supply/supplier-orders/{order['id']}/retry-send")
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["attempt_number"], 2)
        self.assertEqual(retry.json()["recipient_email"], "orders@example.test")
        with self.sessions.begin() as session:
            attempt = session.get(SupplySupplierOrderDeliveryAttempt, UUID(retry.json()["id"]))
            finalize_supplier_order_email(
                session, attempt.automation_execution_id, succeeded=True,
                completed_at=datetime.now(timezone.utc),
                provider_message_id="message-42",
            )
        detail = self.client.get(f"/supply/supplier-orders/{order['id']}").json()
        self.assertEqual(detail["status"], "SENT")
        self.assertIsNotNone(detail["sent_at"])
        self.assertEqual(detail["latest_delivery_attempt"]["status"], "SUCCEEDED")
        self.assertEqual(detail["latest_delivery_attempt"]["provider_message_id"], "message-42")
        self.assertEqual(len(detail["delivery_history"]), 2)
        self.assertEqual(self.client.post(f"/supply/supplier-orders/{order['id']}/send").status_code, 409)
        self.assertEqual(self.client.post(f"/supply/supplier-orders/{order['id']}/cancel").status_code, 409)

    def test_supplier_order_email_send_invariants_and_tenant(self) -> None:
        draft = self.create_supplier_order(status="DRAFT")
        self.assertEqual(self.client.post(f"/supply/supplier-orders/{draft['id']}/send").status_code, 409)
        cancelled = self.create_supplier_order(status="CANCELLED")
        self.assertEqual(self.client.post(f"/supply/supplier-orders/{cancelled['id']}/send").status_code, 409)
        ready = self.create_supplier_order()
        self.assertEqual(self.client.post(f"/supply/supplier-orders/{ready['id']}/send").status_code, 409)
        self.current_user_id = 3
        self.assertEqual(self.client.post(f"/supply/supplier-orders/{ready['id']}/send").status_code, 404)

    def test_supplier_order_email_callback_is_idempotent_and_fail_closed(self) -> None:
        order = self.create_supplier_order()
        self.client.post(
            f"/supply/supplier-orders/{order['id']}/prepare-message",
            json={"responsible_phone": "+7 900 000-00-00"},
        )
        queued = self.client.post(f"/supply/supplier-orders/{order['id']}/send").json()
        store = SqlAlchemyOutboxStore(self.sessions)
        claimed = store.claim_next(worker_id="callback-test", claimed_at=datetime.now(timezone.utc))
        store.mark_published(
            claimed,
            acceptance=CommandAcceptance(provider="n8n", accepted=True, status_code=202),
            published_at=datetime.now(timezone.utc),
        )
        with self.sessions() as session:
            execution_id = str(session.get(
                SupplySupplierOrderDeliveryAttempt, UUID(queued["id"])
            ).automation_execution_id)
        previous_token = settings.automation_callback_token
        settings.automation_callback_token = SecretStr("callback-test-token")
        callback = {
            "contract_version": "1.0", "execution_id": execution_id,
            "status": "succeeded",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "result": {"provider_message_id": "provider-99"},
            "error_code": None, "error_message": None,
        }
        try:
            first = self.client.post(
                "/automation/callback", json=callback,
                headers={"Authorization": "Bearer callback-test-token"},
            )
            duplicate = self.client.post(
                "/automation/callback", json=callback,
                headers={"Authorization": "Bearer callback-test-token"},
            )
            stale_failure = self.client.post(
                "/automation/callback", json={
                    **callback, "status": "failed", "result": None,
                    "error_code": "LATE_FAILURE", "error_message": "late",
                },
                headers={"Authorization": "Bearer callback-test-token"},
            )
        finally:
            settings.automation_callback_token = previous_token
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(stale_failure.status_code, 409, stale_failure.text)
        detail = self.client.get(f"/supply/supplier-orders/{order['id']}").json()
        self.assertEqual(detail["status"], "SENT")
        self.assertEqual(detail["latest_delivery_attempt"]["provider_message_id"], "provider-99")

    def test_supplier_order_email_queue_rollback_leaves_no_attempt_or_command(self) -> None:
        order = self.create_supplier_order()
        self.client.post(
            f"/supply/supplier-orders/{order['id']}/prepare-message",
            json={"responsible_phone": "+7 900 000-00-00"},
        )
        with self.sessions() as session, patch(
            "app.supply.supplier_order_delivery.create_automation_execution",
            side_effect=RuntimeError("synthetic failure"),
        ):
            with self.assertRaises(RuntimeError):
                queue_supplier_order_email(
                    session, UUID(order["id"]), tenant_id="eclair", user_id=2,
                )
        with self.sessions() as session:
            self.assertEqual(len(session.scalars(select(SupplySupplierOrderDeliveryAttempt)).all()), 0)
            self.assertEqual(len(session.scalars(select(AutomationExecution)).all()), 0)
            self.assertEqual(len(session.scalars(select(OutboxEvent)).all()), 0)

    def _sent_order(self):
        order = self.create_supplier_order(delivery_date="2026-09-20")
        with self.sessions.begin() as session:
            stored = session.get(SupplySupplierOrder, UUID(order["id"]))
            stored.status = "SENT"
            stored.sent_at = datetime.now(timezone.utc)
        return self.client.get(f"/supply/supplier-orders/{order['id']}").json()

    def _create_supplier_document(
        self, order: dict, *, document_type="INVOICE", number=None,
    ) -> dict:
        response = self.client.post(
            f"/supply/supplier-orders/{order['id']}/documents",
            json={
                "document_type": document_type,
                "document_number": number or f"DOC-{uuid4().hex[:8]}",
                "document_date": "2026-09-17",
                "create_obligation": document_type in ("INVOICE", "UPD"),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _record_acceptance_case(self, *, received: str, accepted: str, rejected: str):
        order = self._sent_order()
        created = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances",
            json={"destination_mapping_id": str(self.destination_mapping.id)},
        )
        self.assertEqual(created.status_code, 201, created.text)
        acceptance = created.json()
        line = acceptance["lines"][0]
        with self.sessions.begin() as session:
            session.get(SupplySupplierAcceptanceLine, UUID(line["id"])).documented_quantity = Decimal("10")
        payload = {
            "received_quantity": received,
            "accepted_quantity": accepted,
            "rejected_quantity": rejected,
        }
        if Decimal(rejected) > 0:
            payload["rejection_reason"] = "DAMAGED"
        changed = self.client.patch(
            f"/supply/supplier-acceptances/{acceptance['id']}/lines/{line['id']}",
            json=payload,
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        recorded = self.client.post(
            f"/supply/supplier-acceptances/{acceptance['id']}/record"
        )
        self.assertEqual(recorded.status_code, 200, recorded.text)
        return recorded.json()

    def test_supplier_confirmation_revision_defaults_record_history_and_immutability(self) -> None:
        order = self._sent_order()
        created = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations")
        self.assertEqual(created.status_code, 200, created.text)
        draft = created.json()
        self.assertEqual(draft["revision_number"], 1)
        self.assertEqual(draft["status"], "DRAFT")
        self.assertEqual(draft["confirmed_delivery_date"], "2026-09-20")
        self.assertEqual(draft["lines"][0]["confirmed_packages_count"], 2)
        self.assertEqual(draft["lines"][0]["confirmed_price_per_package"], "4956.00")
        repeated = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations")
        self.assertEqual(repeated.json()["id"], draft["id"])

        patched = self.client.patch(f"/supply/supplier-confirmations/{draft['id']}", json={
            "supplier_reference": " SUP-42 ", "confirmed_delivery_date": "2026-09-21",
            "responded_at": "2026-09-17T10:00:00+05:00",
        })
        self.assertEqual(patched.status_code, 200, patched.text)
        line = patched.json()["lines"][0]
        changed = self.client.patch(
            f"/supply/supplier-confirmations/{draft['id']}/lines/{line['id']}",
            json={"response_status": "CHANGED", "confirmed_packages_count": 1,
                  "confirmed_price_per_package": "5100.00"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["confirmed_total_amount"], "5100.000000")
        self.assertEqual(changed.json()["lines"][0]["confirmed_quantity_base"], "12.000000")
        recorded = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/record")
        self.assertEqual(recorded.status_code, 200, recorded.text)
        self.assertEqual(recorded.json()["status"], "RECORDED")
        self.assertEqual(recorded.json()["response_type"], "PARTIALLY_CONFIRMED")
        self.assertEqual(recorded.json()["supplier_confirmation_review_state"], "REQUIRES_DECISION")
        self.assertEqual(
            {item["deviation_type"] for item in recorded.json()["deviations"]},
            {"QUANTITY_CHANGED", "PRICE_CHANGED", "DELIVERY_DATE_CHANGED"},
        )
        quantity_deviation = next(
            item for item in recorded.json()["deviations"]
            if item["deviation_type"] == "QUANTITY_CHANGED"
        )
        accepted = self.client.post(
            f"/supply/supplier-confirmation-deviations/{quantity_deviation['id']}/decision",
            json={"decision": "ACCEPT", "comment": "Принимаем одну упаковку"},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(
            next(item for item in accepted.json()["deviations"] if item["id"] == quantity_deviation["id"])["status"],
            "RESOLVED",
        )
        self.assertEqual(self.client.post(
            f"/supply/supplier-confirmation-deviations/{quantity_deviation['id']}/decision",
            json={"decision": "REJECT"},
        ).status_code, 409)
        self.assertEqual(self.client.patch(
            f"/supply/supplier-confirmations/{draft['id']}", json={"supplier_reference": "X"}
        ).status_code, 409)

        second = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations").json()
        self.assertEqual(second["revision_number"], 2)
        self.assertEqual(second["supplier_reference"], "SUP-42")
        self.assertEqual(second["lines"][0]["confirmed_packages_count"], 1)
        second_line = second["lines"][0]
        rejected = self.client.patch(
            f"/supply/supplier-confirmations/{second['id']}/lines/{second_line['id']}",
            json={"response_status": "REJECTED", "supplier_line_comment": "Нет в наличии"},
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertIsNone(rejected.json()["lines"][0]["confirmed_price_per_package"])
        recorded_two = self.client.post(f"/supply/supplier-confirmations/{second['id']}/record")
        self.assertEqual(recorded_two.json()["response_type"], "REJECTED")
        history = self.client.get(f"/supply/supplier-orders/{order['id']}/confirmations").json()
        self.assertEqual([item["status"] for item in history], ["RECORDED", "SUPERSEDED"])
        detail = self.client.get(f"/supply/supplier-orders/{order['id']}").json()
        self.assertEqual(detail["status"], "SENT")
        self.assertEqual(detail["supplier_confirmation_state"], "REJECTED")
        self.assertEqual(detail["confirmation_history_count"], 2)
        self.assertEqual(detail["supplier_confirmation_review_state"], "REQUIRES_DECISION")
        first = next(item for item in history if item["revision_number"] == 1)
        preserved = next(item for item in first["deviations"] if item["id"] == quantity_deviation["id"])
        self.assertEqual(preserved["decision_type"], "ACCEPT")

    def test_supplier_confirmation_state_cancel_and_tenant_guards(self) -> None:
        ready = self.create_supplier_order()
        self.assertEqual(self.client.post(
            f"/supply/supplier-orders/{ready['id']}/confirmations"
        ).status_code, 409)
        order = self._sent_order()
        draft = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations").json()
        cancelled = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        replacement = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations")
        self.assertEqual(replacement.json()["revision_number"], 2)
        foreign_unit = self.client.patch(
            f"/supply/supplier-confirmations/{replacement.json()['id']}/lines/{replacement.json()['lines'][0]['id']}",
            json={"confirmed_package_unit_id": str(self.other_unit.id)},
        )
        self.assertEqual(foreign_unit.status_code, 409)
        self.current_user_id = 3
        self.assertEqual(self.client.get(
            f"/supply/supplier-confirmations/{replacement.json()['id']}"
        ).status_code, 404)

    def test_supplier_confirmation_basis_is_enforced_on_record(self) -> None:
        order = self._sent_order()
        draft = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations").json()
        line = draft["lines"][0]
        changed_unit = self.client.patch(
            f"/supply/supplier-confirmations/{draft['id']}/lines/{line['id']}",
            json={"confirmed_package_unit_id": str(self.unit_two.id)},
        )
        self.assertEqual(changed_unit.status_code, 200, changed_unit.text)
        rejected = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/record")
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertIn("единицу или размер упаковки", rejected.json()["detail"])

        restored = self.client.patch(
            f"/supply/supplier-confirmations/{draft['id']}/lines/{line['id']}",
            json={"confirmed_package_unit_id": str(self.unit.id), "confirmed_package_quantity": "10.000"},
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        rejected = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/record")
        self.assertEqual(rejected.status_code, 409, rejected.text)
        with self.sessions() as session:
            stored = session.get(SupplySupplierConfirmation, UUID(draft["id"]))
            self.assertEqual(stored.status, "DRAFT")
            self.assertEqual(session.query(SupplySupplierConfirmationDeviation).count(), 0)

    def test_supplier_confirmation_deviation_comparison_and_clean_case(self) -> None:
        order = self._sent_order()
        draft = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations").json()
        exact = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/record")
        self.assertEqual(exact.status_code, 200, exact.text)
        self.assertEqual(exact.json()["deviations"], [])
        self.assertEqual(exact.json()["supplier_confirmation_review_state"], "CLEAN")

        order = self._sent_order()
        draft = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations").json()
        line = draft["lines"][0]
        changed = self.client.patch(
            f"/supply/supplier-confirmations/{draft['id']}/lines/{line['id']}",
            json={
                "response_status": "CHANGED", "confirmed_packages_count": 3,
                "confirmed_price_per_package": "5500.01",
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        recorded = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/record")
        self.assertEqual(recorded.status_code, 200, recorded.text)
        deviations = {item["deviation_type"]: item for item in recorded.json()["deviations"]}
        self.assertEqual(set(deviations), {"QUANTITY_CHANGED", "PRICE_CHANGED"})
        self.assertTrue(deviations["QUANTITY_CHANGED"]["requires_decision"])
        self.assertTrue(deviations["PRICE_CHANGED"]["requires_decision"])
        self.assertEqual(deviations["QUANTITY_CHANGED"]["quantity_delta"], "12.000000")

    def test_supplier_confirmation_price_threshold_and_decrease_policy(self) -> None:
        cases = (
            ("5203.80", False),
            ("5451.60", False),
            ("5452.10", True),
            ("3964.80", False),
        )
        for confirmed_price, requires_decision in cases:
            with self.subTest(confirmed_price=confirmed_price):
                order = self._sent_order()
                draft = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations").json()
                line = draft["lines"][0]
                changed = self.client.patch(
                    f"/supply/supplier-confirmations/{draft['id']}/lines/{line['id']}",
                    json={"response_status": "CHANGED", "confirmed_price_per_package": confirmed_price},
                )
                self.assertEqual(changed.status_code, 200, changed.text)
                recorded = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/record")
                self.assertEqual(recorded.status_code, 200, recorded.text)
                price = next(item for item in recorded.json()["deviations"] if item["deviation_type"] == "PRICE_CHANGED")
                self.assertEqual(price["requires_decision"], requires_decision)
                self.assertEqual(
                    recorded.json()["supplier_confirmation_review_state"],
                    "REQUIRES_DECISION" if requires_decision else "CLEAN",
                )

    def test_supplier_confirmation_rejection_date_decision_and_tenant_guard(self) -> None:
        order = self._sent_order()
        draft = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations").json()
        line = draft["lines"][0]
        changed = self.client.patch(
            f"/supply/supplier-confirmations/{draft['id']}/lines/{line['id']}",
            json={"response_status": "REJECTED"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        recorded = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/record")
        self.assertEqual(recorded.status_code, 200, recorded.text)
        self.assertEqual(
            [item["deviation_type"] for item in recorded.json()["deviations"]],
            ["LINE_REJECTED"],
        )

        deviation = recorded.json()["deviations"][0]
        self.current_user_id = 3
        self.assertEqual(self.client.post(
            f"/supply/supplier-confirmation-deviations/{deviation['id']}/decision",
            json={"decision": "REJECT"},
        ).status_code, 404)
        self.current_user_id = 2
        decided = self.client.post(
            f"/supply/supplier-confirmation-deviations/{deviation['id']}/decision",
            json={"decision": "REJECT", "comment": "Не принимаем отказ поставщика"},
        )
        self.assertEqual(decided.status_code, 200, decided.text)
        self.assertEqual(decided.json()["supplier_confirmation_review_state"], "RESOLVED")
        self.assertEqual(decided.json()["open_required_deviations_count"], 0)

        order = self._sent_order()
        draft = self.client.post(f"/supply/supplier-orders/{order['id']}/confirmations").json()
        changed = self.client.patch(
            f"/supply/supplier-confirmations/{draft['id']}",
            json={"confirmed_delivery_date": "2026-09-22"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        recorded = self.client.post(f"/supply/supplier-confirmations/{draft['id']}/record")
        date_deviation = recorded.json()["deviations"][0]
        self.assertEqual(date_deviation["deviation_type"], "DELIVERY_DATE_CHANGED")
        self.assertEqual(date_deviation["delivery_delta_days"], 2)
        self.assertTrue(date_deviation["requires_decision"])

    def test_supplier_document_crud_pricing_total_record_cancel_and_duplicate(self) -> None:
        ready = self.create_supplier_order()
        self.assertEqual(self.client.post(
            f"/supply/supplier-orders/{ready['id']}/documents",
            json={"document_type": "INVOICE"},
        ).status_code, 409)

        order = self._sent_order()
        document = self._create_supplier_document(order, number="INV-FOUNDATION")
        self.assertEqual(document["status"], "DRAFT")
        self.assertIsNone(document["supplier_confirmation_id"])
        self.assertEqual(len(document["lines"]), 1)
        self.assertEqual(document["lines"][0]["pricing_basis"], "PACKAGE")
        self.assertEqual(document["lines"][0]["packages_count"], 2)
        self.assertEqual(document["lines"][0]["price_per_package"], "4956.00")
        self.assertEqual(document["total_amount"], "9912.000000")

        duplicate = self.client.post(
            f"/supply/supplier-orders/{order['id']}/documents",
            json={
                "document_type": "INVOICE", "document_number": "INV-FOUNDATION",
                "document_date": "2026-09-17",
            },
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertIn("таким номером", duplicate.json()["detail"])

        fixed = self.client.post(
            f"/supply/supplier-documents/{document['id']}/lines",
            json={
                "product_name_snapshot": "Доставка",
                "pricing_basis": "FIXED_AMOUNT", "line_amount": "500.123456",
            },
        )
        self.assertEqual(fixed.status_code, 200, fixed.text)
        self.assertTrue(fixed.json()["lines"][-1]["is_extra_line"])
        unit_line = self.client.post(
            f"/supply/supplier-documents/{document['id']}/lines",
            json={
                "product_name_snapshot": "Дополнительная услуга",
                "pricing_basis": "UNIT", "quantity_base": "1.234567",
                "package_unit_id_snapshot": str(self.unit.id), "unit_price": "2.345678",
            },
        )
        self.assertEqual(unit_line.status_code, 200, unit_line.text)
        unit = unit_line.json()["lines"][-1]
        self.assertEqual(unit["line_amount"], "2.895897")
        self.assertEqual(unit_line.json()["total_amount"], "10415.019353")

        fixed_line = next(
            item for item in unit_line.json()["lines"]
            if item["product_name_snapshot"] == "Доставка"
        )
        patched = self.client.patch(
            f"/supply/supplier-documents/{document['id']}/lines/{fixed_line['id']}",
            json={"line_amount": "550.00"},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        deleted = self.client.delete(
            f"/supply/supplier-documents/{document['id']}/lines/{unit['id']}"
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["total_amount"], "10462.000000")

        recorded = self.client.post(f"/supply/supplier-documents/{document['id']}/record")
        self.assertEqual(recorded.status_code, 200, recorded.text)
        self.assertEqual(recorded.json()["status"], "RECORDED")
        self.assertEqual(self.client.patch(
            f"/supply/supplier-documents/{document['id']}", json={"comment": "Поздно"},
        ).status_code, 409)
        self.assertEqual(self.client.delete(
            f"/supply/supplier-documents/{document['id']}/lines/{fixed_line['id']}"
        ).status_code, 409)
        self.assertEqual(self.client.post(
            f"/supply/supplier-documents/{document['id']}/cancel"
        ).status_code, 409)

        for document_type in ("DELIVERY_NOTE", "UPD"):
            created = self._create_supplier_document(order, document_type=document_type)
            cancelled = self.client.post(
                f"/supply/supplier-documents/{created['id']}/cancel"
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            self.assertEqual(cancelled.json()["status"], "CANCELLED")
        detail = self.client.get(f"/supply/supplier-orders/{order['id']}").json()
        summary = detail["supplier_documents_summary"]
        self.assertEqual(summary["total_documents"], 3)
        self.assertEqual(summary["invoices_count"], 1)
        self.assertEqual(summary["delivery_notes_count"], 1)
        self.assertEqual(summary["upd_count"], 1)
        self.assertEqual(summary["recorded_documents_count"], 1)

    def test_supplier_payment_api_partial_overpayment_draft_and_filters(self) -> None:
        order = self._sent_order()
        document = self._create_supplier_document(order, number="INV-PAYMENT-API")
        patched = self.client.patch(
            f"/supply/supplier-documents/{document['id']}",
            json={"payment_due_date": "2026-09-16"},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        recorded_document = self.client.post(
            f"/supply/supplier-documents/{document['id']}/record"
        )
        self.assertEqual(recorded_document.status_code, 200, recorded_document.text)

        created = self.client.post("/supply/supplier-payments", json={
            "supplier_id": order["supplier_id"],
            "supplier_document_id": document["id"],
            "supplier_order_id": order["id"],
            "payment_type": "POSTPAYMENT",
            "payment_date": "2026-09-17",
            "amount": "3000.000001",
            "payment_order_number": "PAY-API-1",
            "payment_order_date": "2026-09-17",
            "comment": "Первый платёж",
        })
        self.assertEqual(created.status_code, 201, created.text)
        draft = created.json()
        self.assertEqual(draft["status"], "DRAFT")
        changed = self.client.patch(
            f"/supply/supplier-payments/{draft['id']}", json={"amount": "3000.500001"}
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        recorded = self.client.post(f"/supply/supplier-payments/{draft['id']}/record")
        self.assertEqual(recorded.status_code, 200, recorded.text)
        self.assertEqual(recorded.json()["recorded_by_display_name"], "Admin")
        self.assertEqual(self.client.patch(
            f"/supply/supplier-payments/{draft['id']}", json={"amount": "1"}
        ).status_code, 409)
        self.assertEqual(self.client.post(
            f"/supply/supplier-payments/{draft['id']}/cancel"
        ).status_code, 409)

        detail = self.client.get(f"/supply/supplier-documents/{document['id']}").json()
        self.assertEqual(detail["payment_state"], "PARTIALLY_PAID")
        self.assertEqual(detail["recorded_payments_amount"], "3000.500001")
        self.assertEqual(detail["overdue_state"], "OVERDUE")
        payment_list = self.client.get(
            "/supply/supplier-payments",
            params={"supplier_id": order["supplier_id"], "status": "RECORDED", "payment_order_number": "PAY-API"},
        )
        self.assertEqual(payment_list.status_code, 200, payment_list.text)
        self.assertEqual(payment_list.json()["total"], 1)

        duplicate = self.client.post("/supply/supplier-payments", json={
            "supplier_id": order["supplier_id"],
            "supplier_document_id": document["id"],
            "supplier_order_id": order["id"],
            "payment_type": "POSTPAYMENT",
            "payment_date": "2026-09-17",
            "amount": "3000.500001",
            "payment_order_number": "PAY-API-1",
            "payment_order_date": "2026-09-17",
        })
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(duplicate.json()["detail"], "Платёжное поручение уже зарегистрировано")

    def test_supplier_document_defaults_follow_confirmation_fact_not_decision(self) -> None:
        cases = (
            ("LINE_REJECTED", "ACCEPT"), ("LINE_REJECTED", "REJECT"),
            ("QUANTITY_CHANGED", "ACCEPT"), ("QUANTITY_CHANGED", "REJECT"),
            ("PRICE_CHANGED", "ACCEPT"), ("PRICE_CHANGED", "REJECT"),
        )
        for deviation_type, decision in cases:
            with self.subTest(deviation_type=deviation_type, decision=decision):
                order = self._sent_order()
                draft = self.client.post(
                    f"/supply/supplier-orders/{order['id']}/confirmations"
                ).json()
                line = draft["lines"][0]
                if deviation_type == "LINE_REJECTED":
                    changes = {"response_status": "REJECTED"}
                elif deviation_type == "QUANTITY_CHANGED":
                    changes = {"response_status": "CHANGED", "confirmed_packages_count": 1}
                else:
                    changes = {
                        "response_status": "CHANGED",
                        "confirmed_price_per_package": "6000.00",
                    }
                changed = self.client.patch(
                    f"/supply/supplier-confirmations/{draft['id']}/lines/{line['id']}",
                    json=changes,
                )
                self.assertEqual(changed.status_code, 200, changed.text)
                recorded = self.client.post(
                    f"/supply/supplier-confirmations/{draft['id']}/record"
                ).json()
                deviation = next(
                    item for item in recorded["deviations"]
                    if item["deviation_type"] == deviation_type
                )
                order_before = self.client.get(
                    f"/supply/supplier-orders/{order['id']}"
                ).json()
                confirmation_before = self.client.get(
                    f"/supply/supplier-confirmations/{draft['id']}"
                ).json()
                decided = self.client.post(
                    f"/supply/supplier-confirmation-deviations/{deviation['id']}/decision",
                    json={"decision": decision},
                )
                self.assertEqual(decided.status_code, 200, decided.text)
                order_after = self.client.get(
                    f"/supply/supplier-orders/{order['id']}"
                ).json()
                confirmation_after = self.client.get(
                    f"/supply/supplier-confirmations/{draft['id']}"
                ).json()
                self.assertEqual(order_after["lines"], order_before["lines"])
                confirmation_snapshot_fields = (
                    "response_status", "confirmed_packages_count",
                    "confirmed_package_quantity", "confirmed_package_unit_id",
                    "confirmed_quantity_base", "confirmed_price_per_package",
                    "confirmed_planned_amount", "supplier_line_comment",
                )
                self.assertEqual(
                    {
                        field: confirmation_after["lines"][0][field]
                        for field in confirmation_snapshot_fields
                    },
                    {
                        field: confirmation_before["lines"][0][field]
                        for field in confirmation_snapshot_fields
                    },
                )

                document = self._create_supplier_document(order)
                self.assertEqual(document["supplier_confirmation_id"], draft["id"])
                self.assertEqual(document["supplier_confirmation_revision"], 1)
                if deviation_type == "LINE_REJECTED":
                    self.assertEqual(document["lines"], [])
                    if decision == "ACCEPT":
                        manually_added = self.client.post(
                            f"/supply/supplier-documents/{document['id']}/lines",
                            json={
                                "supplier_order_line_id": line["supplier_order_line_id"],
                                "product_name_snapshot": "Сахар по внешнему документу",
                                "pricing_basis": "PACKAGE", "packages_count": 1,
                                "package_quantity_snapshot": "12.000",
                                "package_unit_id_snapshot": str(self.unit.id),
                                "price_per_package": "5100.00",
                            },
                        )
                        self.assertEqual(manually_added.status_code, 200, manually_added.text)
                        self.assertEqual(manually_added.json()["lines"][0]["line_amount"], "5100.000000")
                        fixed = self.client.post(
                            f"/supply/supplier-documents/{document['id']}/record"
                        )
                        self.assertEqual(fixed.status_code, 200, fixed.text)
                elif deviation_type == "QUANTITY_CHANGED":
                    self.assertEqual(document["lines"][0]["packages_count"], 1)
                    self.assertEqual(document["lines"][0]["quantity_base"], "12.000000")
                    self.assertEqual(
                        document["lines"][0]["supplier_confirmation_line_id"], line["id"],
                    )
                else:
                    self.assertEqual(document["lines"][0]["price_per_package"], "6000.00")

    def test_supplier_document_unresolved_review_and_link_guards(self) -> None:
        order = self._sent_order()
        draft = self.client.post(
            f"/supply/supplier-orders/{order['id']}/confirmations"
        ).json()
        line = draft["lines"][0]
        self.client.patch(
            f"/supply/supplier-confirmations/{draft['id']}/lines/{line['id']}",
            json={"response_status": "CHANGED", "confirmed_packages_count": 1},
        )
        recorded = self.client.post(
            f"/supply/supplier-confirmations/{draft['id']}/record"
        ).json()
        document = self._create_supplier_document(order)
        self.assertEqual(document["lines"], [])
        added = self.client.post(
            f"/supply/supplier-documents/{document['id']}/lines",
            json={
                "product_name_snapshot": "Доставка", "pricing_basis": "FIXED_AMOUNT",
                "line_amount": "100.00",
            },
        )
        self.assertEqual(added.status_code, 200, added.text)
        blocked = self.client.post(
            f"/supply/supplier-documents/{document['id']}/record"
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("обязательным отклонениям", blocked.json()["detail"])

        quantity = next(
            item for item in recorded["deviations"]
            if item["deviation_type"] == "QUANTITY_CHANGED"
        )
        self.client.post(
            f"/supply/supplier-confirmation-deviations/{quantity['id']}/decision",
            json={"decision": "REJECT"},
        )
        self.assertEqual(self.client.post(
            f"/supply/supplier-documents/{document['id']}/record"
        ).status_code, 200)

        other_order = self._sent_order()
        other_document = self._create_supplier_document(other_order)
        foreign_line = self.client.post(
            f"/supply/supplier-documents/{other_document['id']}/lines",
            json={
                "supplier_order_line_id": line["supplier_order_line_id"],
                "product_name_snapshot": "Чужая строка", "pricing_basis": "PACKAGE",
                "packages_count": 1, "price_per_package": "1.00",
            },
        )
        self.assertEqual(foreign_line.status_code, 409, foreign_line.text)
        foreign_unit = self.client.post(
            f"/supply/supplier-documents/{other_document['id']}/lines",
            json={
                "product_name_snapshot": "Чужая единица", "pricing_basis": "UNIT",
                "quantity_base": "1", "unit_price": "1",
                "package_unit_id_snapshot": str(self.other_unit.id),
            },
        )
        self.assertEqual(foreign_unit.status_code, 409, foreign_unit.text)

    def test_supplier_document_attachments_upload_read_delete_and_validate(self) -> None:
        order = self._sent_order()
        document = self._create_supplier_document(order, document_type="UPD")
        previous_dir = settings.supplier_document_upload_dir
        with tempfile.TemporaryDirectory() as upload_dir:
            settings.supplier_document_upload_dir = upload_dir
            try:
                uploaded = self.client.post(
                    f"/supply/supplier-documents/{document['id']}/attachments",
                    files={"file": ("УПД-123.pdf", b"%PDF-1.4 test", "application/pdf")},
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                attachment = uploaded.json()["attachments"][0]
                self.assertEqual(attachment["original_filename"], "УПД-123.pdf")
                opened = self.client.get(
                    f"/supply/supplier-documents/{document['id']}/attachments/{attachment['id']}"
                )
                self.assertEqual(opened.status_code, 200, opened.text)
                self.assertEqual(opened.content, b"%PDF-1.4 test")
                self.assertEqual(opened.headers["content-type"], "application/pdf")

                invalid = self.client.post(
                    f"/supply/supplier-documents/{document['id']}/attachments",
                    files={"file": ("script.svg", b"<svg/>", "image/svg+xml")},
                )
                self.assertEqual(invalid.status_code, 422, invalid.text)

                deleted = self.client.delete(
                    f"/supply/supplier-documents/{document['id']}/attachments/{attachment['id']}"
                )
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertEqual(deleted.json()["attachments"], [])
            finally:
                settings.supplier_document_upload_dir = previous_dir

    def test_supplier_acceptance_document_defaults_partial_remaining_and_immutability(self) -> None:
        order = self._sent_order()
        document = self._create_supplier_document(order, document_type="DELIVERY_NOTE")
        extra = self.client.post(
            f"/supply/supplier-documents/{document['id']}/lines",
            json={"product_name_snapshot": "Доставка", "pricing_basis": "FIXED_AMOUNT", "line_amount": "100"},
        )
        self.assertEqual(extra.status_code, 200, extra.text)
        recorded_document = self.client.post(
            f"/supply/supplier-documents/{document['id']}/record"
        )
        self.assertEqual(recorded_document.status_code, 200, recorded_document.text)
        with self.sessions() as session:
            document_total = session.get(
                SupplySupplierDocument, UUID(document["id"])
            ).total_amount
            financial_counts = (
                session.query(SupplySupplierPayment).count(),
                session.query(SupplySupplierPaymentAllocation).count(),
                session.query(SupplySupplierSettlementAdjustment).count(),
            )

        created = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances",
            json={
                "supplier_document_id": document["id"],
                "destination_mapping_id": str(self.destination_mapping.id),
                "comment": "Первая машина",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        acceptance = created.json()
        self.assertEqual(acceptance["source"], "DOCUMENT")
        self.assertEqual(acceptance["destination_mapping_id"], str(self.destination_mapping.id))
        self.assertEqual(acceptance["destination"]["department_name"], "М15")
        self.assertEqual(acceptance["destination"]["role"], "MAIN")
        self.assertEqual(acceptance["destination"]["iiko_store_name"], "Основной склад М15")
        self.assertEqual(len(acceptance["lines"]), 1)
        self.assertEqual(acceptance["lines"][0]["documented_quantity"], "24.000000")
        self.assertIsNone(acceptance["lines"][0]["ordered_vs_confirmed"])
        self.assertIsNone(acceptance["lines"][0]["confirmed_vs_documented"])
        self.assertEqual(acceptance["lines"][0]["documented_vs_received"], "0.000000")
        self.assertEqual(acceptance["lines"][0]["received_vs_accepted"], "0.000000")

        line = acceptance["lines"][0]
        invalid = self.client.patch(
            f"/supply/supplier-acceptances/{acceptance['id']}/lines/{line['id']}",
            json={"received_quantity": "18", "accepted_quantity": "16", "rejected_quantity": "2"},
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)
        changed = self.client.patch(
            f"/supply/supplier-acceptances/{acceptance['id']}/lines/{line['id']}",
            json={"received_quantity": "18", "accepted_quantity": "16", "rejected_quantity": "2", "rejection_reason": "DAMAGED"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["lines"][0]["shortage_quantity"], "6.000000")
        fixed = self.client.post(f"/supply/supplier-acceptances/{acceptance['id']}/record")
        self.assertEqual(fixed.status_code, 200, fixed.text)
        self.assertEqual(fixed.json()["result"], "PARTIALLY_ACCEPTED")
        self.assertEqual(fixed.json()["open_issues_count"], 2)
        self.assertEqual(fixed.json()["lines"][0]["downstream_accepted_quantity"], "16.000000")
        self.assertEqual(fixed.json()["lines"][0]["receipt_eligible_quantity"], "16.000000")
        self.assertEqual(self.client.patch(
            f"/supply/supplier-acceptances/{acceptance['id']}", json={"comment": "late"},
        ).status_code, 409)
        self.assertEqual(self.client.patch(
            f"/supply/supplier-acceptances/{acceptance['id']}",
            json={"destination_mapping_id": None},
        ).status_code, 409)

        second = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances",
            json={
                "supplier_document_id": document["id"],
                "destination_mapping_id": str(self.destination_mapping.id),
            },
        )
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["lines"][0]["documented_quantity"], "6.000000")
        second_recorded = self.client.post(
            f"/supply/supplier-acceptances/{second.json()['id']}/record"
        )
        self.assertEqual(second_recorded.status_code, 200, second_recorded.text)
        detail = self.client.get(f"/supply/supplier-orders/{order['id']}").json()
        self.assertEqual(detail["acceptance_summary"]["recorded_count"], 2)
        self.assertTrue(detail["acceptance_summary"]["has_shortage"])
        cumulative = detail["acceptance_summary"]["cumulative_lines"]
        self.assertEqual(len(cumulative), 1)
        self.assertEqual(cumulative[0]["source_quantity"], "24.000000")
        self.assertEqual(cumulative[0]["total_received"], "24.000000")
        self.assertEqual(cumulative[0]["total_accepted"], "22.000000")
        self.assertEqual(cumulative[0]["total_rejected"], "2.000000")
        self.assertEqual(cumulative[0]["remaining_quantity"], "0.000000")
        unit_totals = next(iter(
            detail["acceptance_summary"]["quantities_by_unit"].values()
        ))
        self.assertEqual(unit_totals["documented"], "24.000000")
        with self.sessions() as session:
            self.assertEqual(
                session.get(SupplySupplierDocument, UUID(document["id"])).total_amount,
                document_total,
            )
            self.assertEqual(financial_counts, (
                session.query(SupplySupplierPayment).count(),
                session.query(SupplySupplierPaymentAllocation).count(),
                session.query(SupplySupplierSettlementAdjustment).count(),
            ))

    def test_supplier_acceptance_fallback_chain_and_sent_guard(self) -> None:
        ready = self.create_supplier_order()
        blocked = self.client.post(
            f"/supply/supplier-orders/{ready['id']}/acceptances", json={},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)

        order = self._sent_order()
        from_order = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances", json={},
        )
        self.assertEqual(from_order.status_code, 201, from_order.text)
        self.assertEqual(from_order.json()["source"], "ORDER")
        self.assertEqual(from_order.json()["lines"][0]["ordered_quantity"], "24.000000")
        self.assertIsNone(from_order.json()["lines"][0]["confirmed_quantity"])
        self.assertIsNone(from_order.json()["lines"][0]["documented_quantity"])
        self.client.post(f"/supply/supplier-acceptances/{from_order.json()['id']}/cancel")

        confirmation = self.client.post(
            f"/supply/supplier-orders/{order['id']}/confirmations"
        ).json()
        recorded = self.client.post(
            f"/supply/supplier-confirmations/{confirmation['id']}/record"
        )
        self.assertEqual(recorded.status_code, 200, recorded.text)
        from_confirmation = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances", json={},
        )
        self.assertEqual(from_confirmation.status_code, 201, from_confirmation.text)
        self.assertEqual(from_confirmation.json()["source"], "CONFIRMATION")
        self.assertEqual(from_confirmation.json()["lines"][0]["confirmed_quantity"], "24.000000")
        self.assertIsNone(from_confirmation.json()["lines"][0]["documented_quantity"])
        self.assertEqual(
            from_confirmation.json()["lines"][0]["ordered_vs_confirmed"],
            "0.000000",
        )

    def test_supplier_acceptance_requires_valid_destination_before_record(self) -> None:
        order = self._sent_order()
        created = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances", json={},
        )
        self.assertEqual(created.status_code, 201, created.text)
        acceptance_id = created.json()["id"]
        blocked = self.client.post(
            f"/supply/supplier-acceptances/{acceptance_id}/record"
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertEqual(blocked.json()["detail"], "Выберите действующий склад приёмки")
        foreign = self.client.patch(
            f"/supply/supplier-acceptances/{acceptance_id}",
            json={"destination_mapping_id": str(uuid4())},
        )
        self.assertEqual(foreign.status_code, 422, foreign.text)
        updated = self.client.patch(
            f"/supply/supplier-acceptances/{acceptance_id}",
            json={"destination_mapping_id": str(self.destination_mapping.id)},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(
            updated.json()["destination"]["iiko_store_code"], "M15-MAIN"
        )
        recorded = self.client.post(
            f"/supply/supplier-acceptances/{acceptance_id}/record"
        )
        self.assertEqual(recorded.status_code, 200, recorded.text)

    def test_acceptance_excess_uses_documented_quantity_accepted_first(self) -> None:
        fully_accepted = self._record_acceptance_case(
            received="12", accepted="12", rejected="0"
        )
        self.assertEqual(fully_accepted["resolution_state"], "OPEN_ISSUES")
        self.assertEqual(
            [(item["issue_type"], item["quantity"]) for item in fully_accepted["resolutions"]],
            [("EXCESS", "2.000000")],
        )
        self.assertEqual(fully_accepted["lines"][0]["accepted_excess_quantity"], "2.000000")
        self.assertIsNone(fully_accepted["lines"][0]["receipt_eligible_quantity"])

        rejected_excess = self._record_acceptance_case(
            received="12", accepted="10", rejected="2"
        )
        self.assertNotIn(
            "EXCESS", {item["issue_type"] for item in rejected_excess["resolutions"]}
        )
        self.assertEqual(
            [(item["issue_type"], item["quantity"]) for item in rejected_excess["resolutions"]],
            [("REJECTED", "2.000000")],
        )

        mixed = self._record_acceptance_case(
            received="12", accepted="11", rejected="1"
        )
        issues = {item["issue_type"]: item for item in mixed["resolutions"]}
        self.assertEqual(issues["EXCESS"]["quantity"], "1.000000")
        self.assertEqual(issues["REJECTED"]["quantity"], "1.000000")

        rejected = self.client.post(
            f"/supply/acceptance-resolutions/{fully_accepted['resolutions'][0]['id']}/resolve",
            json={"resolution_type": "REJECT_EXCESS"},
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["downstream_accepted_quantity"], "10.000000")
        refreshed = self.client.get(
            f"/supply/supplier-acceptances/{fully_accepted['id']}"
        ).json()
        self.assertEqual(refreshed["lines"][0]["downstream_accepted_quantity"], "10.000000")
        self.assertEqual(refreshed["lines"][0]["receipt_eligible_quantity"], "10.000000")
        with self.sessions() as session:
            line = session.get(
                SupplySupplierAcceptanceLine,
                UUID(fully_accepted["resolutions"][0]["acceptance_line_id"]),
            )
            self.assertEqual(line.accepted_quantity, Decimal("12.000000"))

        accepted = self.client.post(
            f"/supply/acceptance-resolutions/{issues['EXCESS']['id']}/resolve",
            json={"resolution_type": "ACCEPT_EXCESS"},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["downstream_accepted_quantity"], "11.000000")
        self.assertEqual(self.client.post(
            f"/supply/acceptance-resolutions/{issues['EXCESS']['id']}/resolve",
            json={"resolution_type": "REJECT_EXCESS"},
        ).status_code, 409)

    def test_acceptance_shortage_returns_canonical_need_with_order_date(self) -> None:
        acceptance = self._record_acceptance_case(
            received="8", accepted="8", rejected="0"
        )
        shortage = acceptance["resolutions"][0]
        self.assertEqual(shortage["issue_type"], "SHORTAGE")
        resolved = self.client.post(
            f"/supply/acceptance-resolutions/{shortage['id']}/resolve",
            json={"resolution_type": "RETURN_TO_PROCUREMENT"},
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        need = resolved.json()["procurement_need"]
        self.assertEqual(need["quantity"], "2.000")
        self.assertEqual(need["reason"], "SUPPLIER_SHORTAGE")
        self.assertEqual(need["status"], "OPEN")
        self.assertEqual(need["need_date"], (date.today() + timedelta(days=1)).isoformat())
        self.assertEqual(self.client.post(
            f"/supply/acceptance-resolutions/{shortage['id']}/resolve",
            json={"resolution_type": "CLOSE_SHORTAGE"},
        ).status_code, 409)

        request_id = self.create_request()["id"]
        collected = self.client.post(
            f"/supply/purchase-requests/{request_id}/collect-needs"
        )
        self.assertEqual(collected.status_code, 200, collected.text)
        self.assertEqual(collected.json()["lines"][0]["quantity"], "2.000")
        self.assertEqual(
            collected.json()["lines"][0]["sources"][0]["procurement_need_id"],
            need["id"],
        )
        trace = collected.json()["lines"][0]["sources"][0]["procurement_need"]["acceptance_resolution_info"]
        self.assertEqual(trace["id"], shortage["id"])
        self.assertEqual(trace["supplier_acceptance_id"], acceptance["id"])
        self.assertEqual(trace["acceptance_line_id"], shortage["acceptance_line_id"])
        self.assertEqual(trace["issue_type"], "SHORTAGE")

    def test_acceptance_resolution_wait_close_manual_and_transaction_rollback(self) -> None:
        shortage_wait = self._record_acceptance_case(
            received="8", accepted="8", rejected="0"
        )["resolutions"][0]
        waited = self.client.post(
            f"/supply/acceptance-resolutions/{shortage_wait['id']}/resolve",
            json={"resolution_type": "WAIT_FOR_DELIVERY", "comment": "Довезут завтра"},
        )
        self.assertEqual(waited.status_code, 200, waited.text)
        self.assertIsNone(waited.json()["procurement_need"])

        shortage_close = self._record_acceptance_case(
            received="9", accepted="9", rejected="0"
        )["resolutions"][0]
        closed = self.client.post(
            f"/supply/acceptance-resolutions/{shortage_close['id']}/resolve",
            json={"resolution_type": "CLOSE_SHORTAGE"},
        )
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertIsNone(closed.json()["procurement_need"])

        rejection = self._record_acceptance_case(
            received="10", accepted="8", rejected="2"
        )
        rejected_issue = next(
            item for item in rejection["resolutions"] if item["issue_type"] == "REJECTED"
        )
        replacement = self.client.post(
            f"/supply/acceptance-resolutions/{rejected_issue['id']}/resolve",
            json={"resolution_type": "WAIT_FOR_REPLACEMENT"},
        )
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertIsNone(replacement.json()["procurement_need"])

        order = self._sent_order()
        created = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances",
            json={"destination_mapping_id": str(self.destination_mapping.id)},
        ).json()
        manual = self.client.post(
            f"/supply/supplier-acceptances/{created['id']}/lines",
            json={
                "product_name_snapshot": "Неизвестный товар", "unit_id": str(self.unit.id),
                "received_quantity": "1", "accepted_quantity": "0", "rejected_quantity": "1",
                "rejection_reason": "WRONG_PRODUCT",
            },
        )
        self.assertEqual(manual.status_code, 200, manual.text)
        recorded = self.client.post(
            f"/supply/supplier-acceptances/{created['id']}/record"
        )
        self.assertEqual(recorded.status_code, 200, recorded.text)
        manual_issue = next(
            item for item in recorded.json()["resolutions"]
            if item["product_name"] == "Неизвестный товар"
        )
        blocked = self.client.post(
            f"/supply/acceptance-resolutions/{manual_issue['id']}/resolve",
            json={"resolution_type": "RETURN_TO_PROCUREMENT", "need_date": "2026-09-30"},
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertIn("сопоставленные товар и единица", blocked.json()["detail"])

        order = self._sent_order()
        draft = self.client.post(
            f"/supply/supplier-orders/{order['id']}/acceptances",
            json={"destination_mapping_id": str(self.destination_mapping.id)},
        ).json()
        line_id = draft["lines"][0]["id"]
        with self.sessions.begin() as session:
            line = session.get(SupplySupplierAcceptanceLine, UUID(line_id))
            line.documented_quantity = Decimal("10")
        self.client.patch(
            f"/supply/supplier-acceptances/{draft['id']}/lines/{line_id}",
            json={"received_quantity": "8", "accepted_quantity": "8", "rejected_quantity": "0"},
        )
        with patch(
            "app.supply.supplier_acceptances._generate_resolution_issues",
            side_effect=RuntimeError("synthetic issue generation failure"),
        ), self.assertRaises(RuntimeError):
            self.client.post(f"/supply/supplier-acceptances/{draft['id']}/record")
        with self.sessions() as session:
            stored = session.get(SupplySupplierAcceptance, UUID(draft["id"]))
            self.assertEqual(stored.status, "DRAFT")
            self.assertEqual(session.query(SupplyAcceptanceResolution).filter_by(
                supplier_acceptance_id=stored.id
            ).count(), 0)

        self.current_user_id = 3
        self.assertEqual(self.client.get(
            f"/supply/acceptance-resolutions/{shortage_close['id']}"
        ).status_code, 404)

    def test_acceptance_clean_combined_and_rejected_resolution_types(self) -> None:
        clean = self._record_acceptance_case(
            received="10", accepted="10", rejected="0"
        )
        self.assertEqual(clean["resolution_state"], "CLEAN")
        self.assertEqual(clean["resolutions"], [])

        combined = self._record_acceptance_case(
            received="8", accepted="7", rejected="1"
        )
        self.assertEqual(
            {item["issue_type"] for item in combined["resolutions"]},
            {"SHORTAGE", "REJECTED"},
        )
        with self.sessions.begin() as session:
            stored = session.get(SupplySupplierAcceptance, UUID(combined["id"]))
            _generate_resolution_issues(session, stored)
            _generate_resolution_issues(session, stored)
        with self.sessions() as session:
            self.assertEqual(session.query(SupplyAcceptanceResolution).filter_by(
                supplier_acceptance_id=UUID(combined["id"])
            ).count(), 2)

        closed_case = self._record_acceptance_case(
            received="10", accepted="9", rejected="1"
        )
        closed_issue = next(
            item for item in closed_case["resolutions"] if item["issue_type"] == "REJECTED"
        )
        closed = self.client.post(
            f"/supply/acceptance-resolutions/{closed_issue['id']}/resolve",
            json={"resolution_type": "CLOSE_REJECTION"},
        )
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertIsNone(closed.json()["procurement_need"])

        return_case = self._record_acceptance_case(
            received="10", accepted="8", rejected="2"
        )
        return_issue = next(
            item for item in return_case["resolutions"] if item["issue_type"] == "REJECTED"
        )
        returned = self.client.post(
            f"/supply/acceptance-resolutions/{return_issue['id']}/resolve",
            json={"resolution_type": "RETURN_TO_PROCUREMENT"},
        )
        self.assertEqual(returned.status_code, 200, returned.text)
        self.assertEqual(returned.json()["procurement_need"]["quantity"], "2.000")
        self.assertEqual(
            returned.json()["procurement_need"]["reason"], "SUPPLIER_REJECTION"
        )


if __name__ == "__main__":
    unittest.main()
