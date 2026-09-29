import os
import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.core.action_context import (
    ActionContextError,
    confirm_shift_substitution,
    resolve_action_context,
)
from app.models.employee import (
    Employee,
    EmployeeDepartmentAssignment,
    EmployeeIikoShift,
    EmployeeIikoShiftStatus,
    EmployeeRole,
    EmployeeRoleAssignment,
    EmployeeStatus,
    ShiftDepartmentConfirmation,
)
from app.models.audit import AuditEvent
from app.models.supply import Department
from app.models.user import User


class ActionContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine,
            "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        Department.__table__.create(self.engine)
        User.__table__.create(self.engine)
        Employee.__table__.create(self.engine)
        EmployeeRoleAssignment.__table__.create(self.engine)
        EmployeeDepartmentAssignment.__table__.create(self.engine)
        EmployeeIikoShift.__table__.create(self.engine)
        ShiftDepartmentConfirmation.__table__.create(self.engine)
        AuditEvent.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.now = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
        self.primary_id = uuid4()
        self.actual_id = uuid4()
        self.employee_id = uuid4()
        with self.sessions.begin() as db:
            db.add_all([
                Department(
                    id=self.primary_id, tenant_id="eclair", code="M15", name="М15"
                ),
                Department(
                    id=self.actual_id, tenant_id="eclair", code="M35", name="М35"
                ),
                User(
                    id=1, username="seller", display_name="Seller",
                    hashed_password="x", tenant_id="eclair", is_active=True,
                ),
                User(
                    id=2, username="unlinked", display_name="Unlinked",
                    hashed_password="x", tenant_id="eclair", is_active=True,
                ),
                User(
                    id=3, username="actor", display_name="Actor",
                    hashed_password="x", tenant_id="eclair", is_active=True,
                ),
            ])
        app.dependency_overrides[get_db] = self.override_get_db
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.client = TestClient(app)
        with self.sessions.begin() as db:
            db.add(Employee(
                id=self.employee_id,
                tenant_id="eclair",
                linked_user_id=1,
                full_name="Продавец",
                birth_date=date(1990, 1, 1),
                phone="1",
                residence_address="x",
            ))
        with self.sessions.begin() as db:
            db.add_all([
                EmployeeRoleAssignment(
                    tenant_id="eclair", employee_id=self.employee_id,
                    role=EmployeeRole.SELLER, valid_from=self.now - timedelta(days=1),
                    reason="Назначение", assigned_by_user_id=3,
                ),
                EmployeeDepartmentAssignment(
                    tenant_id="eclair", employee_id=self.employee_id,
                    department_id=self.primary_id, is_primary=True,
                    valid_from=self.now - timedelta(days=1), reason="Основное",
                    assigned_by_user_id=3,
                ),
                EmployeeDepartmentAssignment(
                    tenant_id="eclair", employee_id=self.employee_id,
                    department_id=self.actual_id, is_primary=False,
                    valid_from=self.now - timedelta(days=1), reason="Дополнительное",
                    assigned_by_user_id=3,
                ),
            ])

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine.dispose()

    def override_get_db(self):
        with self.sessions() as db:
            yield db

    def override_current_user(self):
        with self.sessions() as db:
            return db.get(User, 1)

    def assert_code(self, expected: str, callback) -> None:
        with self.assertRaises(ActionContextError) as caught:
            callback()
        self.assertEqual(caught.exception.code, expected)

    def add_shift(self, db, *, department_id=None, status=EmployeeIikoShiftStatus.OPEN):
        shift_id = uuid4()
        closed_at = self.now if status == EmployeeIikoShiftStatus.CLOSED else None
        db.add(EmployeeIikoShift(
            id=shift_id,
            tenant_id="eclair",
            employee_id=self.employee_id,
            iiko_user_id="iiko-seller",
            external_shift_id=str(shift_id),
            iiko_department_id="iiko-department",
            department_id=department_id,
            opened_at=self.now - timedelta(hours=1),
            closed_at=closed_at,
            duration_minutes=60 if closed_at else None,
            status=status,
            reconciliation_key=str(shift_id),
            first_seen_at=self.now,
            last_seen_at=self.now,
        ))
        db.flush()
        return shift_id

    def test_identity_lifecycle_and_role_guard(self) -> None:
        with self.sessions() as db:
            self.assert_code(
                "EMPLOYEE_NOT_LINKED",
                lambda: resolve_action_context(db, db.get(User, 2), write=False),
            )
            employee = db.get(Employee, self.employee_id)
            employee.status = EmployeeStatus.DISMISSED
            employee.dismissal_date = date(2026, 9, 29)
            employee.dismissal_reason = "Уволен"
            db.flush()
            self.assert_code(
                "EMPLOYEE_DISMISSED",
                lambda: resolve_action_context(db, db.get(User, 1), write=False),
            )
            employee.status = EmployeeStatus.ACTIVE
            employee.dismissal_date = None
            employee.dismissal_reason = None
            db.execute(
                EmployeeRoleAssignment.__table__.delete().where(
                    EmployeeRoleAssignment.employee_id == self.employee_id
                )
            )
            self.assert_code(
                "ROLE_REQUIRED",
                lambda: resolve_action_context(
                    db, db.get(User, 1), write=False,
                    required_roles=frozenset({EmployeeRole.SELLER}),
                ),
            )

    def test_seller_read_without_shift_allowed_but_write_rejected(self) -> None:
        with self.sessions() as db:
            context = resolve_action_context(
                db, db.get(User, 1), write=False,
                required_roles=frozenset({EmployeeRole.SELLER}),
            )
            self.assertEqual(context.actual_department_id, self.primary_id)
            self.assertIsNone(context.shift_id)
            self.assert_code(
                "IIKO_SHIFT_REQUIRED",
                lambda: resolve_action_context(
                    db, db.get(User, 1), write=True,
                    required_roles=frozenset({EmployeeRole.SELLER}),
                    requested_department_id=self.primary_id,
                ),
            )

    def test_admin_role_does_not_inherit_seller_shift_gate(self) -> None:
        with self.sessions() as db:
            db.add(EmployeeRoleAssignment(
                tenant_id="eclair",
                employee_id=self.employee_id,
                role=EmployeeRole.ADMIN,
                valid_from=self.now - timedelta(days=1),
                reason="Администрирование",
                assigned_by_user_id=3,
            ))
            db.flush()
            context = resolve_action_context(
                db,
                db.get(User, 1),
                write=True,
                required_roles=frozenset({EmployeeRole.SELLER, EmployeeRole.ADMIN}),
                role_precedence=(EmployeeRole.ADMIN, EmployeeRole.SELLER),
                requested_department_id=self.primary_id,
            )
            self.assertIsNone(context.shift_id)
            self.assertEqual(context.actual_department_id, self.primary_id)

    def test_resolved_shift_authoritative_and_wrong_department_rejected(self) -> None:
        with self.sessions() as db:
            shift_id = self.add_shift(db, department_id=self.primary_id)
            context = resolve_action_context(
                db, db.get(User, 1), write=True,
                required_roles=frozenset({EmployeeRole.SELLER}),
                requested_department_id=self.primary_id,
            )
            self.assertEqual(context.shift_id, shift_id)
            self.assertEqual(context.actual_department_id, self.primary_id)
            self.assertFalse(context.substitution_confirmed)
            self.assert_code(
                "DEPARTMENT_FORBIDDEN",
                lambda: resolve_action_context(
                    db, db.get(User, 1), write=True,
                    required_roles=frozenset({EmployeeRole.SELLER}),
                    requested_department_id=self.actual_id,
                ),
            )

    def test_unresolved_and_closed_shift_rejected(self) -> None:
        with self.sessions() as db:
            self.add_shift(db, department_id=None)
            self.assert_code(
                "IIKO_SHIFT_DEPARTMENT_UNRESOLVED",
                lambda: resolve_action_context(
                    db, db.get(User, 1), write=True,
                    required_roles=frozenset({EmployeeRole.SELLER}),
                ),
            )
        with self.sessions.begin() as db:
            db.execute(EmployeeIikoShift.__table__.delete())
            self.add_shift(
                db, department_id=self.primary_id,
                status=EmployeeIikoShiftStatus.CLOSED,
            )
        with self.sessions() as db:
            self.assert_code(
                "IIKO_SHIFT_REQUIRED",
                lambda: resolve_action_context(
                    db, db.get(User, 1), write=True,
                    required_roles=frozenset({EmployeeRole.SELLER}),
                ),
            )

    def test_substitution_confirmation_is_shift_specific(self) -> None:
        with self.sessions() as db:
            first_shift = self.add_shift(db, department_id=self.actual_id)
            self.assert_code(
                "SHIFT_SUBSTITUTION_CONFIRMATION_REQUIRED",
                lambda: resolve_action_context(
                    db, db.get(User, 1), write=True,
                    required_roles=frozenset({EmployeeRole.SELLER}),
                    requested_department_id=self.actual_id,
                ),
            )
            confirmed = confirm_shift_substitution(
                db, db.get(User, 1), shift_id=first_shift, at=self.now
            )
            self.assertTrue(confirmed.substitution_confirmed)
            self.assertEqual(
                db.scalar(select(ShiftDepartmentConfirmation).where(
                    ShiftDepartmentConfirmation.shift_id == first_shift
                )).actor_user_id,
                1,
            )
            audit = db.scalar(select(AuditEvent).where(
                AuditEvent.event_type == "SHIFT_SUBSTITUTION_CONFIRMED"
            ))
            self.assertEqual(audit.authorized_as, "SELLER")
            self.assertEqual(audit.primary_department_id, self.primary_id)
            self.assertEqual(audit.actual_department_id, self.actual_id)
            self.assertEqual(audit.shift_id, first_shift)
            shift = db.get(EmployeeIikoShift, first_shift)
            shift.status = EmployeeIikoShiftStatus.CLOSED
            shift.closed_at = self.now
            shift.duration_minutes = 60
            db.commit()
            second_shift = self.add_shift(db, department_id=self.actual_id)
            self.assertNotEqual(first_shift, second_shift)
            self.assert_code(
                "SHIFT_SUBSTITUTION_CONFIRMATION_REQUIRED",
                lambda: resolve_action_context(
                    db, db.get(User, 1), write=True,
                    required_roles=frozenset({EmployeeRole.SELLER}),
                    requested_department_id=self.actual_id,
                ),
            )

    def test_direct_api_write_cannot_bypass_shift_or_spoof_department(self) -> None:
        payload = {
            "department_id": str(self.primary_id),
            "direction_id": str(uuid4()),
            "cycle_id": str(uuid4()),
            "raw_input": "Молоко 1 л",
            "lines": [{"raw_text": "Молоко 1 л"}],
        }
        no_shift = self.client.post("/supply/requests", json=payload)
        self.assertEqual(no_shift.status_code, 403, no_shift.text)
        self.assertEqual(no_shift.json()["detail"]["code"], "IIKO_SHIFT_REQUIRED")

        with self.sessions.begin() as db:
            self.add_shift(db, department_id=self.primary_id)
        spoofed = self.client.post(
            "/supply/requests",
            json={**payload, "department_id": str(self.actual_id)},
        )
        self.assertEqual(spoofed.status_code, 403, spoofed.text)
        self.assertEqual(spoofed.json()["detail"]["code"], "DEPARTMENT_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
