"""Supply roles and request scope at the HTTP boundary."""
import os
import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.employee import Employee, EmployeeDepartmentAssignment, EmployeeIikoShift, EmployeeIikoShiftStatus, EmployeeRole, EmployeeRoleAssignment
from app.models.supply import Department, SupplyRequest, SupplySupplier
from app.models.user import User
from tests import test_supply_api as fixture


class SupplyRbacTests(unittest.TestCase):
    setUp = fixture.SupplyApiTests.setUp
    tearDown = fixture.SupplyApiTests.tearDown
    payload = fixture.SupplyApiTests.payload
    create_cycle = fixture.SupplyApiTests.create_cycle
    create_request = fixture.SupplyApiTests.create_request
    reference_ids = fixture.SupplyApiTests.reference_ids

    def actor(self, user_id: int, *roles: EmployeeRole, department_id=None) -> UUID:
        with self.session_factory.begin() as session:
            session.add(User(id=user_id, username=f"supply-actor-{user_id}", display_name=f"Actor {user_id}",
                             hashed_password="unused", tenant_id="eclair", is_active=True, is_admin=False))
            session.flush()
            employee = Employee(tenant_id="eclair", linked_user_id=user_id, full_name=f"Actor {user_id}",
                                birth_date=date(1990, 1, 1), phone="internal", residence_address="private")
            session.add(employee)
            session.flush()
            for role in roles:
                session.add(EmployeeRoleAssignment(tenant_id="eclair", employee_id=employee.id, role=role,
                    valid_from=datetime.now(UTC) - timedelta(days=1), reason="RBAC fixture", assigned_by_user_id=2))
            if department_id is not None:
                session.add(EmployeeDepartmentAssignment(tenant_id="eclair", employee_id=employee.id,
                    department_id=department_id, is_primary=True, valid_from=datetime.now(UTC) - timedelta(days=1),
                    reason="RBAC fixture", assigned_by_user_id=2))
            return employee.id

    def department(self, code: str) -> UUID:
        with self.session_factory() as session:
            return session.scalar(select(Department.id).where(Department.code == code))

    def test_legacy_flag_does_not_authorize_and_global_read_is_read_only(self):
        self.assertEqual(self.client.post("/public/supply/requests", json={}).status_code, 404)
        self.assertEqual(self.client.get("/public/supply/departments").status_code, 404)
        self.assertEqual(self.client.post("/public/supply/requests/old-token/submit", json={}).status_code, 404)
        request_id = self.create_request()["id"]
        self.current_user_id = 1  # legacy can_view_requests, no linked Employee
        self.assertEqual(self.client.get("/supply/requests").status_code, 403)
        self.actor(30, EmployeeRole.DIRECTOR)
        self.current_user_id = 30
        card = self.client.get(f"/supply/requests/{request_id}")
        self.assertEqual(card.status_code, 200, card.text)
        self.assertEqual(card.json()["allowed_actions"], [])
        self.assertEqual(self.client.post("/supply/requests", json=self.payload()).status_code, 403)
        self.assertEqual(self.client.post(f"/supply/requests/{request_id}/cancel", json={"expected_version": 1, "reason": "Нет"}).status_code, 403)

    def test_retail_and_production_scopes(self):
        retail = self.department("М15")
        production = self.department("ЦЕХ")
        retail_id = self.create_request(department_id=str(retail))["id"]
        production_id = self.create_request(department_id=str(production))["id"]
        self.actor(31, EmployeeRole.NETWORK_MANAGER)
        self.current_user_id = 31
        listed = self.client.get("/supply/requests")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIn(retail_id, [row["id"] for row in listed.json()])
        self.assertNotIn(production_id, [row["id"] for row in listed.json()])
        self.assertEqual(self.client.get(f"/supply/requests/{production_id}").status_code, 403)
        self.assertEqual(self.client.post("/supply/requests", json=self.payload(department_id=str(production))).status_code, 403)
        self.actor(32, EmployeeRole.HEAD_OF_PRODUCTION, department_id=production)
        self.current_user_id = 32
        self.assertEqual(self.client.get(f"/supply/requests/{production_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/supply/requests/{retail_id}").status_code, 403)

    def test_seller_shift_gate_and_manager_reason(self):
        retail = self.department("М15")
        request_id = self.create_request(department_id=str(retail))["id"]
        employee_id = self.actor(33, EmployeeRole.SELLER, department_id=retail)
        self.current_user_id = 33
        self.assertEqual(self.client.get(f"/supply/requests/{request_id}").status_code, 200)
        self.assertEqual(self.client.post("/supply/requests", json=self.payload(department_id=str(retail))).status_code, 403)
        with self.session_factory.begin() as session:
            now = datetime.now(UTC)
            session.add(EmployeeIikoShift(tenant_id="eclair", employee_id=employee_id,
                iiko_user_id="seller-33", department_id=retail, opened_at=now,
                first_seen_at=now, last_seen_at=now, status=EmployeeIikoShiftStatus.OPEN,
                reconciliation_key="seller-33-open"))
        self.assertEqual(self.client.post("/supply/requests", json=self.payload(department_id=str(retail))).status_code, 201)
        self.actor(34, EmployeeRole.SUPPLY_MANAGER)
        self.current_user_id = 34
        no_reason = self.client.patch(f"/supply/requests/{request_id}/details", json={
            "expected_version": 1, "raw_input": "Другое описание",
        })
        self.assertEqual(no_reason.status_code, 422, no_reason.text)
        too_long_reason = self.client.patch(f"/supply/requests/{request_id}/details", json={
            "expected_version": 1, "raw_input": "Другое описание", "reason": "x" * 1001,
        })
        self.assertEqual(too_long_reason.status_code, 422, too_long_reason.text)
        changed = self.client.patch(f"/supply/requests/{request_id}/details", json={
            "expected_version": 1, "raw_input": "Другое описание", "reason": "Уточнение заявки",
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(request_id))
            self.assertEqual(item.raw_input, "Другое описание")
            event = session.scalar(select(AuditEvent).where(AuditEvent.entity_id == request_id,
                                                            AuditEvent.operation == "UPDATE"))
            self.assertEqual(event.reason, "Уточнение заявки")
            self.assertEqual(event.authorized_as, "SUPPLY_MANAGER")

    def test_downstream_role_boundaries(self):
        SupplySupplier.__table__.create(self.engine)
        self.actor(35, EmployeeRole.DIRECTOR)
        self.actor(36, EmployeeRole.ACCOUNTANT)
        self.actor(37, EmployeeRole.NETWORK_MANAGER)
        self.current_user_id = 35
        self.assertEqual(self.client.get("/supply/suppliers").status_code, 200)
        self.assertEqual(self.client.post("/supply/suppliers", json={"display_name": "Тест"}).status_code, 403)
        self.current_user_id = 36
        self.assertEqual(self.client.get("/supply/suppliers").status_code, 200)
        self.assertEqual(self.client.post("/supply/suppliers", json={"display_name": "Тест"}).status_code, 403)
        self.current_user_id = 37
        self.assertEqual(self.client.get("/supply/suppliers").status_code, 403)

    def test_multi_role_read_and_write_choose_permission_specific_role(self):
        request_id = self.create_request()["id"]
        self.actor(38, EmployeeRole.DIRECTOR, EmployeeRole.SUPPLY_MANAGER)
        self.current_user_id = 38
        card = self.client.get(f"/supply/requests/{request_id}")
        self.assertEqual(card.status_code, 200, card.text)
        self.assertIn("EDIT", card.json()["allowed_actions"])
        changed = self.client.patch(f"/supply/requests/{request_id}/details", json={
            "expected_version": 1, "raw_input": "Исправлено руководителем снабжения",
            "reason": "Уточнили потребность",
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        with self.session_factory() as session:
            event = session.scalar(select(AuditEvent).where(
                AuditEvent.entity_id == request_id, AuditEvent.operation == "UPDATE",
            ))
            self.assertEqual(event.authorized_as, "SUPPLY_MANAGER")
        self.actor(39, EmployeeRole.DEPUTY_DIRECTOR)
        self.current_user_id = 39
        self.assertEqual(self.client.get(f"/supply/requests/{request_id}").status_code, 200)
        self.assertEqual(self.client.patch(f"/supply/requests/{request_id}/details", json={
            "expected_version": 2, "raw_input": "Недопустимо",
        }).status_code, 403)

    def test_all_thirteen_roles_direct_api_matrix(self):
        SupplySupplier.__table__.create(self.engine)
        retail = self.department("М15")
        production = self.department("ЦЕХ")
        retail_request = self.create_request(department_id=str(retail))["id"]
        production_request = self.create_request(department_id=str(production))["id"]
        global_read = {EmployeeRole.ADMIN, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR,
                       EmployeeRole.SUPPLY_MANAGER, EmployeeRole.ACCOUNTANT}
        downstream_read = global_read
        supplier_write = {EmployeeRole.ADMIN, EmployeeRole.SUPPLY_MANAGER}
        for index, role in enumerate(EmployeeRole, start=100):
            with self.subTest(role=role.value):
                department_id = (production if role in {EmployeeRole.HEAD_OF_PRODUCTION,
                                 EmployeeRole.CHEF_CONFECTIONER} else retail if role == EmployeeRole.SELLER else None)
                self.actor(index, role, department_id=department_id)
                self.current_user_id = index
                retail_status = 200 if role in global_read | {EmployeeRole.NETWORK_MANAGER, EmployeeRole.SELLER} else 403
                production_status = 200 if role in global_read | {EmployeeRole.HEAD_OF_PRODUCTION,
                                         EmployeeRole.CHEF_CONFECTIONER} else 403
                self.assertEqual(self.client.get(f"/supply/requests/{retail_request}").status_code, retail_status)
                self.assertEqual(self.client.get(f"/supply/requests/{production_request}").status_code, production_status)
                self.assertEqual(self.client.get("/supply/suppliers").status_code,
                                 200 if role in downstream_read else 403)
                if role not in downstream_read:
                    for path in ("/supply/purchase-requests", "/supply/supplier-orders", "/supply/supplier-payments"):
                        self.assertEqual(self.client.get(path).status_code, 403, f"{role.value}: {path}")
                if role in {EmployeeRole.NETWORK_MANAGER, EmployeeRole.SELLER}:
                    card = self.client.get(f"/supply/requests/{retail_request}").json()
                    def keys(value):
                        if isinstance(value, dict):
                            return set(value) | set().union(*(keys(child) for child in value.values()))
                        if isinstance(value, list):
                            return set().union(*(keys(child) for child in value))
                        return set()
                    self.assertFalse({key for key in keys(card) if any(
                        word in key.lower() for word in ("price", "cost", "amount", "supplier")
                    )})
                self.assertEqual(self.client.post("/supply/suppliers", json={"display_name": f"Supplier {index}"}).status_code,
                                 201 if role in supplier_write else 403)
                self.assertEqual(self.client.get("/audit/events").status_code,
                                 200 if role == EmployeeRole.ADMIN else 403)
