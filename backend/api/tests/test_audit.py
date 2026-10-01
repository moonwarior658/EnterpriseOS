import os
import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.audit.service import record_audit_event
from app.core.action_context import resolve_action_context
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditEvent
from app.models.employee import (
    Employee, EmployeeDepartmentAssignment, EmployeeIikoShift, EmployeeRole,
    EmployeeRoleAssignment,
)
from app.models.supply import Department
from app.models.user import User


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        event.listen(self.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        Department.__table__.create(self.engine)
        User.__table__.create(self.engine)
        Employee.__table__.create(self.engine)
        EmployeeRoleAssignment.__table__.create(self.engine)
        EmployeeDepartmentAssignment.__table__.create(self.engine)
        EmployeeIikoShift.__table__.create(self.engine)
        AuditEvent.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
        self.primary_id = uuid4()
        self.actor_ids: dict[int, object] = {}
        roles = {
            1: (EmployeeRole.ADMIN, EmployeeRole.SELLER),
            2: (EmployeeRole.DIRECTOR,),
            3: (EmployeeRole.DEPUTY_DIRECTOR,),
            4: (EmployeeRole.SELLER,),
        }
        with self.sessions.begin() as db:
            db.add(Department(id=self.primary_id, tenant_id="eclair", code="M15", name="М15"))
            for user_id in roles:
                db.add(User(
                    id=user_id, username=f"user-{user_id}", display_name=f"User {user_id}",
                    hashed_password="never-audit", tenant_id="eclair", is_active=True,
                    is_admin=user_id == 1,
                ))
        with self.sessions.begin() as db:
            for user_id, employee_roles in roles.items():
                employee = Employee(
                    tenant_id="eclair", linked_user_id=user_id,
                    full_name=f"Сотрудник {user_id}", birth_date=date(1990, 1, user_id),
                    phone=str(user_id), residence_address="Скрытый адрес",
                )
                db.add(employee)
                db.flush()
                self.actor_ids[user_id] = employee.id
                db.add(EmployeeDepartmentAssignment(
                    tenant_id="eclair", employee_id=employee.id,
                    department_id=self.primary_id, is_primary=True,
                    valid_from=self.now - timedelta(days=1), reason="Основное место",
                    assigned_by_user_id=1,
                ))
                for role in employee_roles:
                    db.add(EmployeeRoleAssignment(
                        tenant_id="eclair", employee_id=employee.id, role=role,
                        valid_from=self.now - timedelta(days=1), reason="Назначение",
                        assigned_by_user_id=1,
                    ))
        self.current_user_id = 1

        def override_get_db():
            with self.sessions() as db:
                yield db

        def override_current_user():
            with self.sessions() as db:
                return db.get(User, self.current_user_id)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine.dispose()

    def admin_context(self, db):
        return resolve_action_context(
            db, db.get(User, 1),
            required_roles=frozenset({EmployeeRole.ADMIN, EmployeeRole.SELLER}),
            role_precedence=(EmployeeRole.ADMIN, EmployeeRole.SELLER),
            write=True,
            at=self.now,
        )

    def create_event(self, db) -> AuditEvent:
        audit = record_audit_event(
            db,
            tenant_id="eclair",
            event_type="TEST_CHANGED",
            entity_type="Employee",
            entity_id=self.actor_ids[4],
            operation="UPDATE",
            context=self.admin_context(db),
            actor_user=db.get(User, 1),
            before={
                "full_name": "До", "hashed_password": "secret",
                "token": "secret", "residence_address": "secret",
            },
            after={"full_name": "После"},
            reason="Проверка аудита",
        )
        db.commit()
        db.refresh(audit)
        return audit

    def test_snapshots_effective_role_security_and_immutability(self) -> None:
        with self.sessions() as db:
            audit = self.create_event(db)
            audit_id = audit.id
            self.assertEqual(audit.active_roles_snapshot, ["ADMIN", "SELLER"])
            self.assertEqual(audit.authorized_as, "ADMIN")
            self.assertEqual(audit.actor_name_snapshot, "Сотрудник 1")
            self.assertEqual(audit.primary_department_name_snapshot, "М15")
            self.assertNotIn("hashed_password", audit.before)
            self.assertNotIn("token", audit.before)
            self.assertNotIn("residence_address", audit.before)
            db.get(Employee, self.actor_ids[1]).full_name = "Новое имя"
            db.get(Department, self.primary_id).name = "Игарская 25В"
            db.commit()
        with self.sessions() as db:
            audit = db.get(AuditEvent, audit_id)
            self.assertEqual(audit.actor_name_snapshot, "Сотрудник 1")
            self.assertEqual(audit.primary_department_name_snapshot, "М15")
            audit.reason = "Переписать историю"
            with self.assertRaisesRegex(RuntimeError, "immutable"):
                db.commit()
            db.rollback()
            audit = db.get(AuditEvent, audit_id)
            db.delete(audit)
            with self.assertRaisesRegex(RuntimeError, "immutable"):
                db.commit()

    def test_correction_is_new_event_and_original_is_unchanged(self) -> None:
        with self.sessions() as db:
            original = self.create_event(db)
            original_before = dict(original.before)
            correction = record_audit_event(
                db,
                tenant_id="eclair",
                event_type="TEST_CORRECTED",
                entity_type="Employee",
                entity_id=self.actor_ids[4],
                operation="CORRECT",
                context=self.admin_context(db),
                actor_user=db.get(User, 1),
                before={"full_name": "После"},
                after={"full_name": "Исправлено"},
                reason="Исправление",
                correction_of_event_id=original.id,
            )
            db.commit()
            self.assertNotEqual(correction.id, original.id)
            self.assertEqual(correction.correction_of_event_id, original.id)
            self.assertEqual(db.get(AuditEvent, original.id).before, original_before)

    def test_transaction_rollback_removes_mutation_and_audit(self) -> None:
        target_id = uuid4()
        with self.sessions() as db:
            db.add(Employee(
                id=target_id, tenant_id="eclair", full_name="Откат",
                birth_date=date(1992, 1, 1), phone="0", residence_address="x",
            ))
            record_audit_event(
                db, tenant_id="eclair", event_type="EMPLOYEE_CREATED",
                entity_type="Employee", entity_id=target_id, operation="CREATE",
                context=self.admin_context(db), actor_user=db.get(User, 1),
                after={"full_name": "Откат"}, reason="Откат транзакции",
            )
            db.rollback()
        with self.sessions() as db:
            self.assertIsNone(db.get(Employee, target_id))
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent)), 0)

    def test_audit_insert_failure_prevents_mutation_commit(self) -> None:
        target_id = uuid4()

        def fail_insert(*_args, **_kwargs):
            raise RuntimeError("audit insert failed")

        event.listen(AuditEvent, "before_insert", fail_insert)
        try:
            with self.sessions() as db:
                db.add(Employee(
                    id=target_id, tenant_id="eclair", full_name="Не коммитить",
                    birth_date=date(1993, 1, 1), phone="0", residence_address="x",
                ))
                record_audit_event(
                    db, tenant_id="eclair", event_type="EMPLOYEE_CREATED",
                    entity_type="Employee", entity_id=target_id, operation="CREATE",
                    context=self.admin_context(db), actor_user=db.get(User, 1),
                    after={"full_name": "Не коммитить"}, reason="Проверка ошибки",
                )
                with self.assertRaisesRegex(RuntimeError, "audit insert failed"):
                    db.commit()
                db.rollback()
        finally:
            event.remove(AuditEvent, "before_insert", fail_insert)
        with self.sessions() as db:
            self.assertIsNone(db.get(Employee, target_id))

    def test_global_audit_access_roles(self) -> None:
        with self.sessions() as db:
            self.create_event(db)
        self.current_user_id = 1
        response = self.client.get("/audit/events")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        for user_id in (2, 3, 4):
            self.current_user_id = user_id
            self.assertEqual(self.client.get("/audit/events").status_code, 403)


if __name__ == "__main__":
    unittest.main()
