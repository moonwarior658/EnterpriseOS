import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.employees.iiko import (
    active_shift, correct_link, create_link, current_link, find_candidates,
    link_history, list_shifts, sync_shifts,
)
from app.integrations.iiko.schemas import IikoEmployeeDto, IikoPersonalShiftDto
from app.models.employee import (
    Employee, EmployeeDepartmentAssignment, EmployeeIikoShift, EmployeeRole,
    EmployeeRoleAssignment, IikoEmployeeLink,
)
from app.models.audit import AuditEvent
from app.models.iiko import IikoWarehouseMapping
from app.models.supply import Department
from app.models.user import User


class FakeIikoProvider:
    def __init__(self, employees):
        self.employees = employees

    async def get_employees(self):
        return self.employees


class EmployeeIikoIdentityTests(unittest.IsolatedAsyncioTestCase):
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
        IikoWarehouseMapping.__table__.create(self.engine)
        IikoEmployeeLink.__table__.create(self.engine)
        EmployeeIikoShift.__table__.create(self.engine)
        AuditEvent.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.department_id = uuid4()
        self.warehouse_id = uuid4()
        self.employee_id = uuid4()
        self.other_employee_id = uuid4()
        self.admin_employee_id = uuid4()
        self.started = datetime(2026, 9, 28, 7, 0, tzinfo=UTC)
        with self.sessions.begin() as db:
            db.add_all([
                Department(id=self.department_id, tenant_id="eclair", code="M15", name="М15"),
                User(id=1, username="admin", display_name="Admin", hashed_password="x", is_active=True, is_admin=True, tenant_id="eclair"),
            ])
            db.flush()
            db.add_all([
                Employee(id=self.admin_employee_id, tenant_id="eclair", linked_user_id=1, full_name="Администратор", birth_date=datetime(1989, 1, 1).date(), phone="0", residence_address="z"),
                Employee(id=self.employee_id, tenant_id="eclair", full_name="Иванов Иван Иванович", birth_date=datetime(1990, 1, 1).date(), phone="1", residence_address="x"),
                Employee(id=self.other_employee_id, tenant_id="eclair", full_name="Иванов Иван Петрович", birth_date=datetime(1991, 1, 1).date(), phone="2", residence_address="y"),
                IikoWarehouseMapping(
                    tenant_id="eclair", iiko_warehouse_id=self.warehouse_id,
                    eos_department_id=self.department_id, source_name="М15",
                    status="CONFIRMED", destination_type="DESTINATION", role="MAIN",
                    is_deleted=False,
                ),
            ])
        with self.sessions.begin() as db:
            db.add_all([
                EmployeeRoleAssignment(
                    tenant_id="eclair", employee_id=self.admin_employee_id,
                    role=EmployeeRole.ADMIN, valid_from=self.started - timedelta(days=1),
                    reason="Администрирование", assigned_by_user_id=1,
                ),
                EmployeeDepartmentAssignment(
                    tenant_id="eclair", employee_id=self.admin_employee_id,
                    department_id=self.department_id, is_primary=True,
                    valid_from=self.started - timedelta(days=1),
                    reason="Основное подразделение", assigned_by_user_id=1,
                ),
            ])
        self.provider = FakeIikoProvider([
            IikoEmployeeDto(external_id="iiko-1", name="Иванов Иван Иванович", code="001"),
            IikoEmployeeDto(external_id="iiko-2", name="Иванов Иван Иванович", code="002"),
        ])

    def tearDown(self) -> None:
        self.engine.dispose()

    def employee(self, db, employee_id=None):
        return db.get(Employee, employee_id or self.employee_id)

    async def test_missing_link_candidate_search_and_manual_choice(self) -> None:
        with self.sessions() as db:
            self.assertIsNone(current_link(db, self.employee(db)))
        candidates = await find_candidates(self.provider, full_name="Иванов Иван Иванович")
        self.assertEqual([item.iiko_user_id for item in candidates], ["iiko-1", "iiko-2"])
        missing = await find_candidates(self.provider, full_name="Петров Пётр Петрович")
        self.assertEqual(missing, [])

    async def test_link_duplicate_forbidden_and_correction_preserves_history(self) -> None:
        with self.sessions() as db:
            first = await create_link(
                db, self.employee(db), iiko_user_id="iiko-1", reason="Подтверждение",
                actor=db.get(User, 1), provider=self.provider, now=self.started,
            )
            self.assertEqual(first.iiko_user_id, "iiko-1")
        with self.sessions() as db:
            with self.assertRaises(HTTPException) as raised:
                await create_link(
                    db, self.employee(db, self.other_employee_id), iiko_user_id="iiko-1",
                    reason="Ошибка", actor=db.get(User, 1), provider=self.provider,
                    now=self.started + timedelta(minutes=1),
                )
            self.assertIn("Иванов Иван Иванович", raised.exception.detail)

        shift = IikoPersonalShiftDto(
            external_id="shift-1", employee_external_id="iiko-1",
            department_external_id=str(self.warehouse_id),
            opened_at=self.started + timedelta(hours=1), closed_at=None,
        )
        with self.sessions() as db:
            sync_shifts(db, [shift], tenant_id="eclair", seen_at=self.started + timedelta(hours=2))
        with self.sessions() as db:
            replacement = await correct_link(
                db, self.employee(db), iiko_user_id="iiko-2", reason="Исправление identity",
                actor=db.get(User, 1), provider=self.provider,
                now=self.started + timedelta(hours=3),
            )
            self.assertEqual(replacement.iiko_user_id, "iiko-2")
            history = link_history(db, self.employee(db))
            self.assertEqual(len(history), 2)
            self.assertEqual(history[1].ended_reason, "Исправление identity")
            stored = db.scalar(select(EmployeeIikoShift))
            self.assertEqual(stored.iiko_user_id, "iiko-2")
            audits = list(db.scalars(select(AuditEvent).where(
                AuditEvent.entity_id == str(self.employee_id),
            ).order_by(AuditEvent.occurred_at)).all())
            self.assertEqual(
                [item.event_type for item in audits],
                ["IIKO_EMPLOYEE_LINK_CREATED", "IIKO_EMPLOYEE_LINK_CORRECTED"],
            )
            self.assertEqual(audits[1].correction_of_event_id, audits[0].id)
            self.assertEqual(audits[1].reason, "Исправление identity")

    async def test_shift_create_repeat_close_duration_mapping_and_history_after_dismissal(self) -> None:
        with self.sessions() as db:
            await create_link(
                db, self.employee(db), iiko_user_id="iiko-1", reason="Подтверждение",
                actor=db.get(User, 1), provider=self.provider, now=self.started,
            )
        opened = self.started + timedelta(hours=1)
        open_fact = IikoPersonalShiftDto(
            external_id="shift-1", employee_external_id="iiko-1",
            department_external_id="unknown-department", opened_at=opened,
        )
        with self.sessions() as db:
            created = sync_shifts(db, [open_fact], tenant_id="eclair", seen_at=opened)
            self.assertEqual((created.created, created.unresolved_department), (1, 1))
        with self.sessions() as db:
            repeated = sync_shifts(db, [open_fact], tenant_id="eclair", seen_at=opened + timedelta(minutes=5))
            self.assertEqual((repeated.created, repeated.unchanged), (0, 1))
            self.assertIsNotNone(active_shift(db, self.employee(db)))
        closed_fact = open_fact.model_copy(update={
            "closed_at": opened + timedelta(hours=8, minutes=17),
            "department_external_id": str(self.warehouse_id),
        })
        with self.sessions() as db:
            closed = sync_shifts(db, [closed_fact], tenant_id="eclair", seen_at=opened + timedelta(hours=9))
            self.assertEqual(closed.updated, 1)
            self.assertIsNone(active_shift(db, self.employee(db)))
            shifts = list_shifts(db, self.employee(db))
            self.assertEqual(shifts[0].duration_minutes, 497)
            self.assertEqual(shifts[0].department_id, self.department_id)
            self.employee(db).status = "DISMISSED"
            self.employee(db).dismissal_date = opened.date()
            self.employee(db).dismissal_reason = "Увольнение"
            db.commit()
        with self.sessions() as db:
            self.assertEqual(len(list_shifts(db, self.employee(db))), 1)


if __name__ == "__main__":
    unittest.main()
