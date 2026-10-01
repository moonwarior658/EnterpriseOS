"""Employee/User RBAC behavior against the existing API and audit model."""

import unittest
import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.employee import Employee, EmployeeRole, EmployeeRoleAssignment, EmployeeDepartmentAssignment, IikoDepartmentMapping
from app.models.iiko import IikoWarehouseMapping, IikoMappingStatus, IikoWarehouseRole, IikoWarehouseDestinationType
from app.models.supply import DepartmentBusinessType
from app.models.user import User
from app.core.action_context import ActionContextError, resolve_action_context
from app.core.authorization import Scope, scoped_department_ids
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

    def test_classification_scope_survives_rename_and_unknowns_fail_closed(self) -> None:
        self.actor(30, EmployeeRole.NETWORK_MANAGER)
        production_id, auto_id, unknown_id = uuid4(), uuid4(), uuid4()
        with self.sessions.begin() as session:
            session.add_all([
                fixture_module.Department(id=production_id, tenant_id="eclair", code="P", name="P",
                                          business_type=DepartmentBusinessType.PRODUCTION),
                fixture_module.Department(id=auto_id, tenant_id="eclair", code="A", name="A",
                                          business_type=DepartmentBusinessType.AUTO),
                fixture_module.Department(id=unknown_id, tenant_id="eclair", code="X", name="X"),
            ])
        with self.sessions() as session:
            user = session.get(User, 30)
            context = resolve_action_context(session, user, write=False)
            self.assertEqual(scoped_department_ids(session, user, Scope.ECLAIR_POINTS, context),
                             {self.department_id, self.other_department_id})
        with self.sessions.begin() as session:
            department = session.get(fixture_module.Department, self.department_id)
            department.code = "RENAMED"
            department.name = "Новое название"
        with self.sessions() as session:
            user = session.get(User, 30)
            context = resolve_action_context(session, user, write=False)
            self.assertEqual(scoped_department_ids(session, user, Scope.ECLAIR_POINTS, context),
                             {self.department_id, self.other_department_id})
        self.current_user_id = 30
        self.assertEqual(self.client.get("/employees/departments").status_code, 200)
        self.assertEqual({item["id"] for item in self.client.get("/employees/departments").json()},
                         {str(self.department_id), str(self.other_department_id), str(auto_id)})

    def test_network_manager_seller_transfer_and_driver_category(self) -> None:
        self.actor(31, EmployeeRole.NETWORK_MANAGER)
        production_id, auto_id = uuid4(), uuid4()
        with self.sessions.begin() as session:
            session.add_all([
                fixture_module.Department(id=production_id, tenant_id="eclair", code="P", name="P",
                                          business_type=DepartmentBusinessType.PRODUCTION),
                fixture_module.Department(id=auto_id, tenant_id="eclair", code="A", name="A",
                                          business_type=DepartmentBusinessType.AUTO),
            ])
        self.current_user_id = 31
        payload = fixture_module.EmployeesApiTests.employee_payload()
        payload["department_id"] = str(self.department_id)
        seller = self.client.post("/employees", json=payload)
        self.assertEqual(seller.status_code, 201, seller.text)
        seller_id = seller.json()["id"]
        start = datetime.now(UTC)
        self.assertEqual(self.client.post(f"/employees/{seller_id}/roles", json={
            "role": "SELLER", "valid_from": start.isoformat(), "reason": "Назначение",
        }).status_code, 201)
        for department_id in (production_id, auto_id, self.other_department_id):
            result = self.client.post(f"/employees/{seller_id}/departments", json={
                "department_id": str(department_id), "is_primary": True,
                "valid_from": start.isoformat(), "reason": "Недопустимое назначение",
            })
            self.assertIn(result.status_code, {403, 409})
        assignment_id = seller.json()["department_assignments"][0]["id"]
        transfer_at = start + timedelta(days=1)
        self.assertEqual(self.client.post(
            f"/employees/{seller_id}/departments/{assignment_id}/end", json={
                "valid_to": transfer_at.isoformat(), "reason": "Перевод",
            }).status_code, 200)
        transfer = self.client.post(f"/employees/{seller_id}/departments", json={
            "department_id": str(self.other_department_id), "is_primary": True,
            "valid_from": transfer_at.isoformat(), "reason": "Новая точка",
        })
        self.assertEqual(transfer.status_code, 201, transfer.text)
        driver_payload = {**payload, "department_id": str(auto_id)}
        driver = self.client.post("/employees", json=driver_payload)
        self.assertEqual(driver.status_code, 201, driver.text)
        driver_id = driver.json()["id"]
        self.assertEqual(self.client.post(f"/employees/{driver_id}/roles", json={
            "role": "DRIVER", "valid_from": datetime.now(UTC).isoformat(), "reason": "Водитель",
        }).status_code, 201)
        self.assertIn(self.client.post(f"/employees/{driver_id}/departments", json={
            "department_id": str(self.department_id), "is_primary": False,
            "valid_from": start.isoformat(), "reason": "Лишнее назначение",
        }).status_code, {403, 409})

    def test_production_roles_require_assigned_production_category(self) -> None:
        with self.sessions.begin() as session:
            session.get(fixture_module.Department, self.other_department_id).business_type = DepartmentBusinessType.PRODUCTION
        for user_id, role in ((32, EmployeeRole.HEAD_OF_PRODUCTION),
                              (33, EmployeeRole.CHEF_CONFECTIONER)):
            self.actor(user_id, role, department_id=self.other_department_id)
            with self.sessions() as session:
                user = session.get(User, user_id)
                context = resolve_action_context(session, user, write=False)
                self.assertEqual(scoped_department_ids(session, user, Scope.PRODUCTION, context),
                                 {self.other_department_id})
                self.assertEqual(resolve_action_context(
                    session, user, write=False, required_roles=frozenset({role}),
                    requested_department_id=self.other_department_id,
                ).actual_department_id, self.other_department_id)
                with self.assertRaises(ActionContextError):
                    resolve_action_context(
                        session, user, write=False, required_roles=frozenset({role}),
                        requested_department_id=self.department_id,
                    )
        with self.sessions.begin() as session:
            session.get(fixture_module.Department, self.other_department_id).business_type = None
        with self.sessions() as session:
            user = session.get(User, 32)
            context = resolve_action_context(session, user, write=False)
            self.assertEqual(scoped_department_ids(session, user, Scope.PRODUCTION, context), set())

    def test_iiko_mappings_do_not_grant_department_scope(self) -> None:
        IikoDepartmentMapping.__table__.create(self.engine)
        IikoWarehouseMapping.__table__.create(self.engine)
        self.actor(34, EmployeeRole.NETWORK_MANAGER)
        production_id = uuid4()
        with self.sessions.begin() as session:
            session.add(fixture_module.Department(
                id=production_id, tenant_id="eclair", code="P", name="P",
                business_type=DepartmentBusinessType.PRODUCTION,
            ))
            session.flush()
            session.add_all([
                IikoDepartmentMapping(
                    tenant_id="eclair", iiko_department_id=uuid4(),
                    eos_department_id=production_id, reason="Тестовый mapping",
                    decided_by_user_id=1,
                ),
                IikoWarehouseMapping(
                    tenant_id="eclair", iiko_warehouse_id=uuid4(),
                    eos_department_id=production_id, source_name="iiko warehouse",
                    destination_type=IikoWarehouseDestinationType.DESTINATION,
                    role=IikoWarehouseRole.MAIN, status=IikoMappingStatus.CONFIRMED,
                    decided_by_user_id=1,
                ),
            ])
        with self.sessions() as session:
            user = session.get(User, 34)
            context = resolve_action_context(session, user, write=False)
            self.assertEqual(scoped_department_ids(session, user, Scope.ECLAIR_POINTS, context),
                             {self.department_id, self.other_department_id})
        with self.sessions.begin() as session:
            session.scalar(select(IikoDepartmentMapping)).eos_department_id = self.department_id
            session.scalar(select(IikoWarehouseMapping)).eos_department_id = self.department_id
        with self.sessions() as session:
            user = session.get(User, 34)
            context = resolve_action_context(session, user, write=False)
            self.assertEqual(scoped_department_ids(session, user, Scope.ECLAIR_POINTS, context),
                             {self.department_id, self.other_department_id})

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
        self.assertEqual(self.client.post(f"/employees/{target}/departments", json={
            "department_id": str(self.department_id), "is_primary": True,
            "valid_from": datetime.now(UTC).isoformat(), "reason": "Торговая точка",
        }).status_code, 201)
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
        with self.sessions.begin() as session:
            session.get(fixture_module.Department, self.other_department_id).business_type = DepartmentBusinessType.PRODUCTION
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
        with self.sessions.begin() as session:
            session.get(fixture_module.Department, self.other_department_id).business_type = DepartmentBusinessType.PRODUCTION
        production = self.target()
        self.assertEqual(self.client.post(f"/employees/{production}/departments", json={
            "department_id": str(self.other_department_id), "is_primary": True,
            "valid_from": datetime.now(UTC).isoformat(), "reason": "Production",
        }).status_code, 201)
        driver = self.target()
        auto_id = uuid4()
        with self.sessions.begin() as session:
            session.add(fixture_module.Department(
                id=auto_id, tenant_id="eclair", code="AUTO", name="Авто",
                business_type=DepartmentBusinessType.AUTO,
            ))
        self.assertEqual(self.client.post(f"/employees/{driver}/departments", json={
            "department_id": str(auto_id), "is_primary": True,
            "valid_from": datetime.now(UTC).isoformat(), "reason": "Авто",
        }).status_code, 201)
        self.assertEqual(self.client.post(f"/employees/{driver}/roles", json={
            "role": "DRIVER", "valid_from": datetime.now(UTC).isoformat(),
            "reason": "Driver work",
        }).status_code, 201)
        self.actor(17, EmployeeRole.HEAD_OF_PRODUCTION, department_id=self.other_department_id)
        self.actor(18, EmployeeRole.SUPPLY_MANAGER)
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
        with self.sessions.begin() as session:
            session.get(fixture_module.Department, self.other_department_id).business_type = DepartmentBusinessType.PRODUCTION
        self.actor(16, EmployeeRole.NETWORK_MANAGER, department_id=self.department_id)
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
        for role in ("SELLER", "HANDYMAN"):
            self.assertEqual(self.client.post(f"/employees/{new_id}/roles", json={
                "role": role, "valid_from": datetime.now(UTC).isoformat(),
                "reason": "Appointment",
            }).status_code, 201)
        self.assertEqual(self.client.post(f"/employees/{new_id}/roles", json={
            "role": "DRIVER", "valid_from": datetime.now(UTC).isoformat(),
            "reason": "Неверное подразделение",
        }).status_code, 409)
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
        self.actor(15, EmployeeRole.SELLER, department_id=self.department_id)
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
