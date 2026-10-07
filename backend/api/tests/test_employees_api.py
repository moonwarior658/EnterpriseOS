import os
import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.employee import (
    Employee, EmployeeDepartmentAssignment, EmployeeIikoShift,
    EmployeeLifecycleEvent, EmployeeRole, EmployeeRoleAssignment,
)
from app.models.audit import AuditEvent
from app.models.supply import Department, DepartmentBusinessType
from app.models.user import User, UserAccountType


class EmployeesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        event.listen(
            self.engine, "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        Department.__table__.create(self.engine)
        Employee.__table__.create(self.engine)
        User.__table__.create(self.engine)
        EmployeeRoleAssignment.__table__.create(self.engine)
        EmployeeDepartmentAssignment.__table__.create(self.engine)
        EmployeeLifecycleEvent.__table__.create(self.engine)
        EmployeeIikoShift.__table__.create(self.engine)
        AuditEvent.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.department_id = uuid4()
        self.other_department_id = uuid4()
        with self.sessions.begin() as session:
            session.add_all([
                Department(id=self.department_id, tenant_id="eclair", code="M15", name="М15", business_type=DepartmentBusinessType.RETAIL_POINT),
                Department(id=self.other_department_id, tenant_id="eclair", code="M35", name="М35", business_type=DepartmentBusinessType.RETAIL_POINT),
                User(
                    id=1, username="admin", display_name="Администратор",
                    hashed_password="unused", is_active=True, is_admin=True, tenant_id="eclair",
                ),
                User(
                    id=2, username="worker", display_name="Сотрудник",
                    hashed_password="unused", is_active=True, is_admin=False, tenant_id="eclair",
                ),
                User(
                    id=3, username="service", display_name="Сервис",
                    hashed_password="unused", is_active=True, is_admin=False, tenant_id="eclair",
                    account_type=UserAccountType.SERVICE,
                ),
                User(
                    id=4, username="other-admin", display_name="Другой администратор",
                    hashed_password="unused", is_active=True, is_admin=True, tenant_id="other",
                ),
            ])
        with self.sessions.begin() as session:
            admin_employee = Employee(
                tenant_id="eclair", linked_user_id=1,
                full_name="Администратор EOS", birth_date=date(1990, 1, 1),
                phone="internal", residence_address="internal",
            )
            session.add(admin_employee)
            session.flush()
            session.add_all([
                EmployeeRoleAssignment(
                    tenant_id="eclair", employee_id=admin_employee.id,
                    role=EmployeeRole.ADMIN,
                    valid_from=datetime.now(UTC) - timedelta(days=1),
                    reason="Администрирование", assigned_by_user_id=1,
                ),
                EmployeeDepartmentAssignment(
                    tenant_id="eclair", employee_id=admin_employee.id,
                    department_id=self.department_id, is_primary=True,
                    valid_from=datetime.now(UTC) - timedelta(days=1),
                    reason="Основное подразделение", assigned_by_user_id=1,
                ),
            ])
            other_admin = Employee(
                tenant_id="other", linked_user_id=4,
                full_name="Другой администратор", birth_date=date(1990, 2, 1),
                phone="internal", residence_address="internal",
            )
            session.add(other_admin)
            session.flush()
            session.add(EmployeeRoleAssignment(
                tenant_id="other", employee_id=other_admin.id,
                role=EmployeeRole.ADMIN,
                valid_from=datetime.now(UTC) - timedelta(days=1),
                reason="Администрирование", assigned_by_user_id=4,
            ))
        self.current_user_id = 1

        def override_get_db():
            with self.sessions() as session:
                yield session

        def override_current_user():
            with self.sessions() as session:
                return session.get(User, self.current_user_id)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine.dispose()

    @staticmethod
    def employee_payload(**changes) -> dict:
        payload = {
            "full_name": " Иванов Иван Иванович ",
            "birth_date": "1990-05-10",
            "photo_url": None,
            "phone": " +7 900 000-00-00 ",
            "residence_address": " Екатеринбург ",
            "reason": " Приём на работу ",
        }
        payload.update(changes)
        return payload

    def create_employee(self, **changes) -> dict:
        response = self.client.post("/employees", json=self.employee_payload(**changes))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def remove_eclair_admin_employee(self) -> None:
        with self.sessions.begin() as session:
            employee_id = session.scalar(select(Employee.id).where(
                Employee.tenant_id == "eclair",
                Employee.linked_user_id == 1,
            ))
            session.execute(delete(EmployeeRoleAssignment).where(
                EmployeeRoleAssignment.employee_id == employee_id,
            ))
            session.execute(delete(EmployeeDepartmentAssignment).where(
                EmployeeDepartmentAssignment.employee_id == employee_id,
            ))
            session.execute(delete(Employee).where(Employee.id == employee_id))

    def bootstrap_payload(self, **changes) -> dict:
        payload = {
            **self.employee_payload(),
            "department_id": str(self.department_id),
        }
        payload.update(changes)
        return payload

    def test_first_admin_bootstrap_is_atomic_audited_and_one_time(self) -> None:
        self.remove_eclair_admin_employee()
        self.assertEqual(self.client.get("/employees").status_code, 403)

        bootstrap_status = self.client.get("/employees/bootstrap")
        self.assertEqual(bootstrap_status.status_code, 200, bootstrap_status.text)
        self.assertEqual(bootstrap_status.json(), {
            "available": True,
            "username": "admin",
            "unavailable_reason": None,
        })

        response = self.client.post("/employees/bootstrap", json=self.bootstrap_payload())
        self.assertEqual(response.status_code, 201, response.text)
        employee = response.json()
        self.assertEqual(employee["linked_user_id"], 1)
        self.assertEqual([item["role"] for item in employee["role_assignments"]], ["ADMIN"])
        self.assertEqual(employee["department_assignments"][0]["department_id"], str(self.department_id))
        self.assertTrue(employee["department_assignments"][0]["is_primary"])
        self.assertEqual(
            {item["event_type"] for item in employee["lifecycle_events"]},
            {"CREATED", "USER_LINKED"},
        )
        self.assertEqual(self.client.get("/employees").status_code, 200)

        with self.sessions() as session:
            self.assertEqual(len(session.scalars(select(User.id).where(
                User.tenant_id == "eclair",
            )).all()), 3)
            events = list(session.scalars(select(AuditEvent).where(
                AuditEvent.entity_id == employee["id"],
            )).all())
            self.assertEqual({item.event_type for item in events}, {
                "FIRST_ADMIN_BOOTSTRAPPED",
                "EMPLOYEE_CREATED",
                "EMPLOYEE_USER_LINKED",
                "EMPLOYEE_ROLE_ASSIGNED",
                "EMPLOYEE_DEPARTMENT_ASSIGNED",
            })
            self.assertTrue(all(item.actor_employee_id is not None for item in events))

        repeat = self.client.post("/employees/bootstrap", json=self.bootstrap_payload())
        self.assertEqual(repeat.status_code, 409, repeat.text)
        status_after = self.client.get("/employees/bootstrap").json()
        self.assertFalse(status_after["available"])
        self.assertEqual(status_after["unavailable_reason"], "CURRENT_USER_ALREADY_LINKED")

    def test_bootstrap_rejects_service_existing_admin_and_rolls_back(self) -> None:
        with self.sessions.begin() as session:
            session.add(User(
                id=5, username="legacy-admin", display_name="Legacy Admin",
                hashed_password="unused", is_active=True, is_admin=True, tenant_id="eclair",
            ))
        self.current_user_id = 5
        status_with_admin = self.client.get("/employees/bootstrap")
        self.assertEqual(status_with_admin.json()["unavailable_reason"], "ADMIN_EMPLOYEE_ALREADY_EXISTS")
        existing_admin = self.client.post("/employees/bootstrap", json=self.bootstrap_payload())
        self.assertEqual(existing_admin.status_code, 409, existing_admin.text)
        self.assertIn("bootstrap навсегда недоступен", existing_admin.json()["detail"])

        self.current_user_id = 1
        self.remove_eclair_admin_employee()
        invalid_department = self.client.post(
            "/employees/bootstrap",
            json=self.bootstrap_payload(department_id=str(uuid4())),
        )
        self.assertEqual(invalid_department.status_code, 404, invalid_department.text)
        with self.sessions() as session:
            self.assertIsNone(session.scalar(select(Employee.id).where(
                Employee.tenant_id == "eclair",
                Employee.linked_user_id == 1,
            )))

        self.current_user_id = 3
        service = self.client.post("/employees/bootstrap", json=self.bootstrap_payload())
        self.assertEqual(service.status_code, 403, service.text)

    def test_create_update_list_and_tenant_isolation(self) -> None:
        employee = self.create_employee()
        self.assertEqual(employee["full_name"], "Иванов Иван Иванович")
        self.assertEqual(employee["status"], "ACTIVE")
        self.assertEqual(employee["lifecycle_events"][0]["event_type"], "CREATED")

        updated = self.client.patch(
            f"/employees/{employee['id']}",
            json={"phone": " +7 999 111-22-33 ", "reason": "Актуализация телефона"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["phone"], "+7 999 111-22-33")
        self.assertIn(
            "UPDATED",
            [item["event_type"] for item in updated.json()["lifecycle_events"]],
        )
        self.assertEqual(self.client.get("/employees").status_code, 200)

        with self.sessions() as session:
            events = list(session.scalars(select(AuditEvent).where(
                AuditEvent.entity_type == "Employee",
                AuditEvent.entity_id == employee["id"],
            )).all())
            self.assertEqual(
                {item.event_type for item in events},
                {"EMPLOYEE_CREATED", "EMPLOYEE_UPDATED"},
            )
            update_event = next(item for item in events if item.event_type == "EMPLOYEE_UPDATED")
            self.assertEqual(update_event.reason, "Актуализация телефона")
            self.assertNotIn("phone", update_event.before)
            self.assertNotIn("residence_address", update_event.before)

        self.current_user_id = 4
        self.assertEqual(self.client.get(f"/employees/{employee['id']}").status_code, 404)
        self.current_user_id = 2
        self.assertEqual(self.client.get("/employees").status_code, 403)

    def test_role_and_department_assignment_history_and_invariants(self) -> None:
        employee = self.create_employee()
        employee_id = employee["id"]
        start = datetime.now(UTC)
        primary = self.client.post(
            f"/employees/{employee_id}/departments",
            json={
                "department_id": str(self.department_id), "is_primary": True,
                "valid_from": start.isoformat(), "reason": "Основное место работы",
            },
        )
        self.assertEqual(primary.status_code, 201, primary.text)
        role = self.client.post(
            f"/employees/{employee_id}/roles",
            json={"role": "SELLER", "valid_from": start.isoformat(), "reason": "Работа продавцом"},
        )
        self.assertEqual(role.status_code, 201, role.text)
        duplicate = self.client.post(
            f"/employees/{employee_id}/roles",
            json={"role": "SELLER", "valid_from": start.isoformat(), "reason": "Повтор"},
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(EmployeeRoleAssignment).where(EmployeeRoleAssignment.employee_id == UUID(employee_id))).all()), 1)
            self.assertEqual(len(db.scalars(select(AuditEvent).where(AuditEvent.entity_id == employee_id, AuditEvent.event_type == 'EMPLOYEE_ROLE_ASSIGNED')).all()), 1)

        second_primary = self.client.post(
            f"/employees/{employee_id}/departments",
            json={
                "department_id": str(self.other_department_id), "is_primary": True,
                "valid_from": start.isoformat(), "reason": "Конфликт основного места",
            },
        )
        self.assertEqual(second_primary.status_code, 409, second_primary.text)
        ended_department = self.client.post(
            f"/employees/{employee_id}/departments/{primary.json()['id']}/end",
            json={"valid_to": (start + timedelta(days=1)).isoformat(), "reason": "Перевод точки"},
        )
        self.assertEqual(ended_department.status_code, 200, ended_department.text)

        ended = self.client.post(
            f"/employees/{employee_id}/roles/{role.json()['id']}/end",
            json={"valid_to": (start + timedelta(days=1)).isoformat(), "reason": "Перевод"},
        )
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertEqual(ended.json()["ended_reason"], "Перевод")
        overlapping = self.client.post(
            f"/employees/{employee_id}/roles",
            json={
                "role": "SELLER", "valid_from": (start + timedelta(hours=12)).isoformat(),
                "reason": "Пересекающееся назначение",
            },
        )
        self.assertEqual(overlapping.status_code, 409, overlapping.text)
        reassigned = self.client.post(
            f"/employees/{employee_id}/roles",
            json={
                "role": "SELLER", "valid_from": (start + timedelta(days=2)).isoformat(),
                "reason": "Новое назначение",
            },
        )
        self.assertEqual(reassigned.status_code, 409, reassigned.text)
        detail = self.client.get(f"/employees/{employee_id}").json()
        self.assertEqual(len(detail["role_assignments"]), 1)
        with self.sessions() as session:
            event_types = set(session.scalars(select(AuditEvent.event_type).where(
                AuditEvent.entity_id == employee_id,
            )).all())
            self.assertTrue({
                "EMPLOYEE_ROLE_ASSIGNED", "EMPLOYEE_ROLE_ENDED",
                "EMPLOYEE_DEPARTMENT_ASSIGNED", "EMPLOYEE_DEPARTMENT_ENDED",
            } <= event_types)

    def test_link_dismiss_reactivate_preserves_identity_and_history(self) -> None:
        employee = self.create_employee()
        employee_id = employee["id"]
        start = datetime.now(UTC)
        self.assertEqual(
            self.client.post(
                f"/employees/{employee_id}/user",
                json={"user_id": 2, "reason": "Выдан доступ в EOS"},
            ).status_code,
            200,
        )
        department = self.client.post(
            f"/employees/{employee_id}/departments",
            json={
                "department_id": str(self.department_id), "is_primary": True,
                "valid_from": start.isoformat(), "reason": "Назначение",
            },
        )
        self.assertEqual(department.status_code, 201, department.text)
        role = self.client.post(
            f"/employees/{employee_id}/roles",
            json={"role": "SELLER", "valid_from": start.isoformat(), "reason": "Назначение"},
        )
        self.assertEqual(role.status_code, 201, role.text)

        dismissed = self.client.post(
            f"/employees/{employee_id}/dismiss",
            json={"dismissal_date": date.today().isoformat(), "reason": "Увольнение по заявлению"},
        )
        self.assertEqual(dismissed.status_code, 200, dismissed.text)
        body = dismissed.json()
        self.assertEqual(body["status"], "DISMISSED")
        self.assertIsNotNone(body["role_assignments"][0]["valid_to"])
        self.assertIsNotNone(body["department_assignments"][0]["valid_to"])
        self.assertEqual(
            self.client.post(
                f"/employees/{employee_id}/dismiss",
                json={"dismissal_date": date.today().isoformat(), "reason": "Повтор"},
            ).status_code,
            409,
        )
        with self.sessions() as session:
            user = session.get(User, 2)
            self.assertFalse(user.is_active)
            self.assertTrue(user.blocked_by_employee_dismissal)
        blocked_activation = self.client.patch("/users/2", json={"is_active": True, "reason": "Повторная активация"})
        self.assertEqual(blocked_activation.status_code, 409, blocked_activation.text)

        reactivated = self.client.post(
            f"/employees/{employee_id}/reactivate",
            json={"effective_date": date.today().isoformat(), "reason": "Повторный приём"},
        )
        self.assertEqual(reactivated.status_code, 200, reactivated.text)
        body = reactivated.json()
        self.assertEqual(body["status"], "ACTIVE")
        self.assertTrue(all(item["valid_to"] is not None for item in body["role_assignments"]))
        self.assertTrue(all(item["valid_to"] is not None for item in body["department_assignments"]))
        self.assertEqual(body["id"], employee_id)
        with self.sessions() as session:
            self.assertTrue(session.get(User, 2).is_active)
            event_types = set(session.scalars(select(AuditEvent.event_type).where(
                AuditEvent.entity_id == employee_id,
            )).all())
            self.assertTrue({
                "EMPLOYEE_USER_LINKED", "EMPLOYEE_DISMISSED", "EMPLOYEE_REACTIVATED",
            } <= event_types)

    def test_link_guards_service_accounts_and_one_to_one(self) -> None:
        first = self.create_employee(full_name="Первый Сотрудник")
        second = self.create_employee(full_name="Второй Сотрудник")
        service_link = self.client.post(
            f"/employees/{first['id']}/user",
            json={"user_id": 3, "reason": "Неверная попытка"},
        )
        self.assertEqual(service_link.status_code, 422, service_link.text)
        linked = self.client.post(
            f"/employees/{first['id']}/user",
            json={"user_id": 2, "reason": "Выдан доступ"},
        )
        self.assertEqual(linked.status_code, 200, linked.text)
        conflict = self.client.post(
            f"/employees/{second['id']}/user",
            json={"user_id": 2, "reason": "Повторная связь"},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        unlinked = self.client.post(
            f"/employees/{first['id']}/user/unlink",
            json={"reason": "Доступ больше не требуется"},
        )
        self.assertEqual(unlinked.status_code, 200, unlinked.text)
        with self.sessions() as session:
            event_types = set(session.scalars(select(AuditEvent.event_type).where(
                AuditEvent.entity_id == first["id"],
            )).all())
            self.assertIn("EMPLOYEE_USER_UNLINKED", event_types)

    def test_password_reset_rotates_linked_human_and_audits_without_plaintext(self) -> None:
        old_password = "old-password-123"
        with self.sessions.begin() as session:
            session.get(User, 2).hashed_password = hash_password(old_password)
        employee = self.create_employee()
        employee_id = employee["id"]
        linked = self.client.post(
            f"/employees/{employee_id}/user",
            json={"user_id": 2, "reason": "Выдан доступ"},
        )
        self.assertEqual(linked.status_code, 200, linked.text)
        self.assertEqual(self.client.post("/auth/token", data={
            "username": "worker", "password": old_password,
        }).status_code, 200)

        reset = self.client.post(
            f"/employees/{employee_id}/password-reset",
            json={"reason": "Плановый сброс администратором"},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        temporary_password = reset.json()["temporary_password"]
        self.assertGreaterEqual(len(temporary_password), 12)
        self.assertNotEqual(temporary_password, old_password)
        self.assertEqual(self.client.post("/auth/token", data={
            "username": "worker", "password": old_password,
        }).status_code, 401)
        self.assertEqual(self.client.post("/auth/token", data={
            "username": "worker", "password": temporary_password,
        }).status_code, 200)

        with self.sessions() as session:
            event = session.scalar(select(AuditEvent).where(
                AuditEvent.event_type == "USER_PASSWORD_RESET",
            ))
            self.assertIsNotNone(event)
            self.assertEqual(event.reason, "Плановый сброс администратором")
            rendered = repr({"before": event.before, "after": event.after})
            self.assertNotIn(old_password, rendered)
            self.assertNotIn(temporary_password, rendered)

        unlinked_employee = self.create_employee(full_name="Без учётной записи")
        self.assertEqual(self.client.post(
            f"/employees/{unlinked_employee['id']}/password-reset",
            json={"reason": "Нельзя"},
        ).status_code, 409)

    def test_blank_reasons_and_delete_are_rejected(self) -> None:
        self.assertEqual(
            self.client.post("/employees", json=self.employee_payload(reason="   ")).status_code,
            422,
        )
        employee = self.create_employee()
        self.assertEqual(self.client.delete(f"/employees/{employee['id']}").status_code, 405)


if __name__ == "__main__":
    unittest.main()
