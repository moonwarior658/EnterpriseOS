"""Employee/User RBAC behavior against the existing API and audit model."""

import unittest
import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.employee import Employee, EmployeeRole, EmployeeRoleAssignment, EmployeeDepartmentAssignment
from app.models.user import User
from app.core.security import hash_password, verify_password
from tests import test_employees_api as fixture_module


class RbacEmployeeUserTests(unittest.TestCase):
    setUp = fixture_module.EmployeesApiTests.setUp
    tearDown = fixture_module.EmployeesApiTests.tearDown

    def actor(self, user_id: int, *roles: EmployeeRole, department_id=None) -> None:
        with self.sessions.begin() as session:
            session.add(User(
                id=user_id, username=f"actor{user_id}", display_name=f"Actor {user_id}",
                hashed_password="unused", is_active=True, is_admin=False, tenant_id="eclair",
            ))
            session.flush()
            employee = Employee(
                tenant_id="eclair", linked_user_id=user_id,
                full_name=f"Actor {user_id}", birth_date=date(1990, 1, 1),
                phone="internal", residence_address="private",
            )
            session.add(employee)
            session.flush()
            for role in roles:
                session.add(EmployeeRoleAssignment(
                    tenant_id="eclair", employee_id=employee.id, role=role,
                    valid_from=datetime.now(UTC) - timedelta(days=1),
                    reason="RBAC fixture", assigned_by_user_id=1,
                ))
            if department_id is not None:
                session.add(EmployeeDepartmentAssignment(
                    tenant_id="eclair", employee_id=employee.id,
                    department_id=department_id, is_primary=True,
                    valid_from=datetime.now(UTC) - timedelta(days=1),
                    reason="RBAC fixture", assigned_by_user_id=1,
                ))

    def target(self) -> str:
        response = self.client.post("/employees", json=fixture_module.EmployeesApiTests.employee_payload())
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_director_reads_employee_and_human_users_but_cannot_write(self) -> None:
        target = self.target()
        self.actor(10, EmployeeRole.DIRECTOR)
        self.current_user_id = 10
        read = self.client.get(f"/employees/{target}")
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["profile_level"], "FULL")
        self.assertEqual(self.client.get("/users").status_code, 200)
        self.assertEqual(self.client.patch(
            f"/employees/{target}", json={"phone": "changed", "reason": "Correction"},
        ).status_code, 403)
        self.assertEqual(self.client.patch(
            "/users/2", json={"is_active": False, "reason": "Correction"},
        ).status_code, 403)

    def test_deputy_write_block_and_escalation_guards(self) -> None:
        target = self.target()
        self.actor(11, EmployeeRole.DEPUTY_DIRECTOR)
        self.current_user_id = 11
        edited = self.client.patch(f"/employees/{target}", json={
            "phone": "new", "reason": "Исправление контакта",
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        with self.sessions() as session:
            audit = session.scalar(select(AuditEvent).where(
                AuditEvent.event_type == "EMPLOYEE_UPDATED",
                AuditEvent.entity_id == target,
            ).order_by(AuditEvent.occurred_at.desc()))
            self.assertEqual(audit.authorized_as, "DEPUTY_DIRECTOR")
        self.assertEqual(self.client.post("/users", json={
            "username": "deputy-created", "display_name": "Test", "account_type": "HUMAN",
        }).status_code, 403)
        for forbidden in ("ADMIN", "DIRECTOR", "DEPUTY_DIRECTOR"):
            self.assertEqual(self.client.post(f"/employees/{target}/roles", json={
                "role": forbidden, "valid_from": datetime.now(UTC).isoformat(),
                "reason": "Escalation attempt",
            }).status_code, 403)
        allowed = self.client.post(f"/employees/{target}/roles", json={
            "role": "SELLER", "valid_from": datetime.now(UTC).isoformat(),
            "reason": "Assignment",
        })
        self.assertEqual(allowed.status_code, 201, allowed.text)
        self.assertEqual(self.client.patch("/users/2", json={
            "is_active": False, "reason": "Доступ больше не нужен",
        }).status_code, 200)
        self.assertEqual(self.client.patch("/users/2", json={
            "is_active": True, "reason": "Доступ восстановлен",
        }).status_code, 200)
        self.assertEqual(self.client.post(f"/employees/{target}/dismiss", json={
            "dismissal_date": date.today().isoformat(), "reason": "Увольнение",
        }).status_code, 200)

    def test_deputy_cannot_reset_and_admin_reset_needs_no_reason(self) -> None:
        target = self.target()
        self.assertEqual(self.client.post(f"/employees/{target}/user", json={
            "user_id": 2, "reason": "Связь с сотрудником",
        }).status_code, 200)
        self.actor(14, EmployeeRole.DEPUTY_DIRECTOR)
        self.current_user_id = 14
        self.assertEqual(self.client.post(f"/employees/{target}/password-reset", json={}).status_code, 403)
        self.current_user_id = 1
        self.assertEqual(self.client.post(f"/employees/{target}/password-reset", json={}).status_code, 200)

    def test_multirole_write_uses_per_permission_precedence(self) -> None:
        target = self.target()
        self.actor(12, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR)
        self.current_user_id = 12
        self.assertEqual(self.client.patch(f"/employees/{target}", json={
            "phone": "multi", "reason": "Исправление",
        }).status_code, 200)
        with self.sessions() as session:
            audit = session.scalar(select(AuditEvent).where(
                AuditEvent.event_type == "EMPLOYEE_UPDATED",
                AuditEvent.entity_id == target,
            ).order_by(AuditEvent.occurred_at.desc()))
            self.assertEqual(audit.authorized_as, "DEPUTY_DIRECTOR")
            self.assertEqual(audit.active_roles_snapshot, ["DEPUTY_DIRECTOR", "DIRECTOR"])

    def test_wide_read_does_not_widen_network_write(self) -> None:
        own = self.target()
        outside = self.target()
        for target, department in ((own, self.department_id), (outside, self.other_department_id)):
            self.assertEqual(self.client.post(f"/employees/{target}/departments", json={
                "department_id": str(department), "is_primary": True,
                "valid_from": datetime.now(UTC).isoformat(), "reason": "Work point",
            }).status_code, 201)
        self.actor(19, EmployeeRole.DIRECTOR, EmployeeRole.NETWORK_MANAGER,
                   department_id=self.department_id)
        self.current_user_id = 19
        with patch("app.core.authorization.ECLAIR_POINT_DEPARTMENT_CODES", frozenset({"M15"})):
            self.assertEqual(self.client.get(f"/employees/{outside}").status_code, 200)
            self.assertEqual(self.client.patch(f"/employees/{outside}", json={
                "phone": "forbidden", "reason": "Attempt",
            }).status_code, 403)
            self.assertEqual(self.client.patch(f"/employees/{own}", json={
                "phone": "allowed", "reason": "Correction",
            }).status_code, 200)
            with self.sessions() as session:
                audit = session.scalar(select(AuditEvent).where(
                    AuditEvent.event_type == "EMPLOYEE_UPDATED",
                    AuditEvent.entity_id == own,
                ).order_by(AuditEvent.occurred_at.desc()))
                self.assertEqual(audit.authorized_as, "NETWORK_MANAGER")

    def test_service_accounts_visible_only_to_admin(self) -> None:
        self.actor(13, EmployeeRole.DIRECTOR)
        self.current_user_id = 13
        self.assertEqual(self.client.get("/users/3").status_code, 404)
        self.assertNotIn(3, [item["id"] for item in self.client.get("/users").json()])
        self.current_user_id = 1
        self.assertEqual(self.client.get("/users/3").status_code, 200)

    def test_basic_profiles_hide_sensitive_fields_and_histories(self) -> None:
        production = self.target()
        self.assertEqual(self.client.post(f"/employees/{production}/departments", json={
            "department_id": str(self.other_department_id), "is_primary": True,
            "valid_from": datetime.now(UTC).isoformat(), "reason": "Production",
        }).status_code, 201)
        driver = self.target()
        self.assertEqual(self.client.post(f"/employees/{driver}/roles", json={
            "role": "DRIVER", "valid_from": datetime.now(UTC).isoformat(),
            "reason": "Driver work",
        }).status_code, 201)
        self.actor(17, EmployeeRole.HEAD_OF_PRODUCTION, department_id=self.other_department_id)
        self.actor(18, EmployeeRole.SUPPLY_MANAGER)
        with patch("app.core.authorization.PRODUCTION_DEPARTMENT_CODES", frozenset({"M35"})):
            self.current_user_id = 17
            profile = self.client.get(f"/employees/{production}")
            self.assertEqual(profile.status_code, 200, profile.text)
            self.assertEqual(profile.json()["profile_level"], "BASIC")
            for field in ("residence_address", "role_assignments", "lifecycle_events", "linked_user_id"):
                self.assertNotIn(field, profile.json())
            self.assertEqual(self.client.get(f"/employees/{driver}").status_code, 403)
        self.current_user_id = 18
        profile = self.client.get(f"/employees/{driver}")
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["profile_level"], "BASIC")
        self.assertEqual(profile.json()["roles"], ["DRIVER"])
        self.assertNotIn("residence_address", profile.json())
        self.assertEqual(self.client.get(f"/employees/{production}").status_code, 403)

    def test_network_manager_scope_roles_and_human_accounts(self) -> None:
        self.actor(16, EmployeeRole.NETWORK_MANAGER, department_id=self.department_id)
        with patch("app.core.authorization.ECLAIR_POINT_DEPARTMENT_CODES", frozenset({"M15"})):
            own = self.target()
            outside = self.target()
            for target, department in ((own, self.department_id), (outside, self.other_department_id)):
                assigned = self.client.post(f"/employees/{target}/departments", json={
                    "department_id": str(department), "is_primary": True,
                    "valid_from": datetime.now(UTC).isoformat(), "reason": "Work point",
                })
                self.assertEqual(assigned.status_code, 201, assigned.text)
            self.current_user_id = 16
            visible = self.client.get("/employees")
            self.assertEqual(visible.status_code, 200, visible.text)
            ids = {item["id"] for item in visible.json()}
            self.assertIn(own, ids)
            self.assertNotIn(outside, ids)
            self.assertEqual(self.client.get(f"/employees/{outside}").status_code, 403)
            self.assertEqual(self.client.post("/employees", json={
                **fixture_module.EmployeesApiTests.employee_payload(),
                "department_id": str(self.other_department_id),
            }).status_code, 403)
            created = self.client.post("/employees", json={
                **fixture_module.EmployeesApiTests.employee_payload(),
                "department_id": str(self.department_id),
            })
            self.assertEqual(created.status_code, 201, created.text)
            new_id = created.json()["id"]
            self.assertEqual(len(created.json()["department_assignments"]), 1)
            for role in ("SELLER", "DRIVER", "HANDYMAN"):
                self.assertEqual(self.client.post(f"/employees/{new_id}/roles", json={
                    "role": role, "valid_from": datetime.now(UTC).isoformat(),
                    "reason": "Appointment",
                }).status_code, 201)
            for role in ("ADMIN", "DIRECTOR", "DEPUTY_DIRECTOR", "ACCOUNTANT"):
                self.assertEqual(self.client.post(f"/employees/{new_id}/roles", json={
                    "role": role, "valid_from": datetime.now(UTC).isoformat(),
                    "reason": "Escalation",
                }).status_code, 403)
            human = self.client.post("/users", json={
                "username": "network.human", "display_name": "Network Human",
                "account_type": "HUMAN", "employee_id": new_id,
            })
            self.assertEqual(human.status_code, 201, human.text)
            self.assertEqual(self.client.post(f"/employees/{new_id}/password-reset", json={}).status_code, 200)
            self.assertEqual(self.client.patch(f"/users/{human.json()['id']}", json={
                "is_active": False, "reason": "Attempt",
            }).status_code, 403)
            self.assertEqual(self.client.post(f"/employees/{new_id}/dismiss", json={
                "dismissal_date": date.today().isoformat(), "reason": "Attempt",
            }).status_code, 403)
            self.assertNotIn(3, {item["id"] for item in self.client.get("/users").json()})

    def test_human_can_change_own_password_with_current_password(self) -> None:
        self.actor(15, EmployeeRole.SELLER)
        with self.sessions.begin() as session:
            session.get(User, 15).hashed_password = hash_password("old-password-123")
        self.current_user_id = 15
        self.assertEqual(self.client.post("/auth/change-password", json={
            "current_password": "wrong-password", "new_password": "new-password-123",
        }).status_code, 403)
        changed = self.client.post("/auth/change-password", json={
            "current_password": "old-password-123", "new_password": "new-password-123",
        })
        self.assertEqual(changed.status_code, 204, changed.text)
        with self.sessions() as session:
            self.assertTrue(verify_password("new-password-123", session.get(User, 15).hashed_password))
            audit = session.scalar(select(AuditEvent).where(AuditEvent.event_type == "USER_PASSWORD_CHANGED"))
            self.assertEqual(audit.authorized_as, "SELLER")

    def test_legacy_unlinked_human_can_change_own_password(self) -> None:
        with self.sessions.begin() as session:
            session.get(User, 2).hashed_password = hash_password("old-password-123")
        self.current_user_id = 2
        changed = self.client.post("/auth/change-password", json={
            "current_password": "old-password-123", "new_password": "new-password-123",
        })
        self.assertEqual(changed.status_code, 204, changed.text)
        with self.sessions() as session:
            self.assertTrue(verify_password("new-password-123", session.get(User, 2).hashed_password))
            audit = session.scalar(select(AuditEvent).where(AuditEvent.event_type == "USER_PASSWORD_CHANGED"))
            self.assertEqual(audit.actor_user_id, 2)
            self.assertIsNone(audit.authorized_as)


if __name__ == "__main__":
    unittest.main()
