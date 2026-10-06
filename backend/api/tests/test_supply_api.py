import os
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.supply import (
    Department,
    DepartmentBusinessType,
    SupplyProduct,
    SupplyProductAlias,
    SupplyDepartmentProductCorrection,
    SupplyDepartmentProductMapping,
    SupplyDepartmentProductMappingAuditEvent,
    SupplyProductCategory,
    SupplyDepartmentDebt,
    SupplyDepartmentDebtEvent,
    SupplyLineAllocation,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyRequestLineDebtLink,
    SupplyStorageZone,
    SupplyUnit,
)
from app.models.user import User
from app.models.audit import AuditEvent
from app.models.employee import (
    Employee,
    EmployeeDepartmentAssignment,
    EmployeeIikoShift,
    EmployeeRole,
    EmployeeRoleAssignment,
    ShiftDepartmentConfirmation,
)
from app.models.work_request import WorkRequest, ExternalContractor, ContractorSpecialization
from app.schemas.supply import SupplyRequestCreate
from app.supply.service import create_supply_request
from app.automation.supply_actions import SupplyAutomationContext, close_expired_request_cycles


DEPARTMENT_DATA = (
    ("М15", "Матросова 15", 10),
    ("М35", "Матросова 35", 20),
    ("И25", "Игарская 25В", 30),
    ("ЦЕХ", "Цех производство", 40),
    ("ATO", "Авто", 50),
)

DIRECTION_DATA = (
    ("MAIN", "Основной", 10),
    ("HOUSEHOLD", "Хозяйственный", 20),
)


class SupplyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.previous_tenant_id = settings.default_tenant_id
        settings.default_tenant_id = "eclair"
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine,
            "connect",
            lambda connection, _: connection.execute(
                "PRAGMA foreign_keys=ON"
            ),
        )
        User.__table__.create(self.engine)
        Department.__table__.create(self.engine)
        Employee.__table__.create(self.engine)
        EmployeeRoleAssignment.__table__.create(self.engine)
        EmployeeDepartmentAssignment.__table__.create(self.engine)
        EmployeeIikoShift.__table__.create(self.engine)
        ShiftDepartmentConfirmation.__table__.create(self.engine)
        AuditEvent.__table__.create(self.engine)
        SupplyRequestDirection.__table__.create(self.engine)
        SupplyRequestCycle.__table__.create(self.engine)
        SupplyUnit.__table__.create(self.engine)
        SupplyProductCategory.__table__.create(self.engine)
        SupplyStorageZone.__table__.create(self.engine)
        SupplyProduct.__table__.create(self.engine)
        SupplyProductAlias.__table__.create(self.engine)
        SupplyDepartmentProductMapping.__table__.create(self.engine)
        ExternalContractor.__table__.create(self.engine)
        ContractorSpecialization.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
        SupplyRequest.__table__.create(self.engine)
        SupplyRequestLine.__table__.create(self.engine)
        SupplyDepartmentProductCorrection.__table__.create(self.engine)
        SupplyDepartmentProductMappingAuditEvent.__table__.create(self.engine)
        SupplyLineAllocation.__table__.create(self.engine)
        SupplyDepartmentDebt.__table__.create(self.engine)
        SupplyDepartmentDebtEvent.__table__.create(self.engine)
        SupplyRequestLineDebtLink.__table__.create(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

        with self.session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        id=1,
                        username="employee",
                        display_name="Сотрудник",
                        hashed_password="unused",
                        is_active=True,
                        is_admin=False,
                        can_view_requests=True,
                    ),
                    User(
                        id=2,
                        username="admin",
                        display_name="Администратор",
                        hashed_password="unused",
                        is_active=True,
                        is_admin=True,
                    ),
                    User(
                        id=3,
                        username="seller",
                        display_name="Продавец",
                        hashed_password="unused",
                        is_active=True,
                        is_admin=False,
                        can_view_requests=False,
                    ),
                ]
            )
            session.add_all(
                [
                    Department(
                        tenant_id="eclair",
                        code=code,
                        name=name,
                        business_type=(DepartmentBusinessType.RETAIL_POINT if code in {"М15", "М35", "И25"}
                                       else DepartmentBusinessType.PRODUCTION if code == "ЦЕХ"
                                       else DepartmentBusinessType.AUTO),
                        display_order=display_order,
                    )
                    for code, name, display_order in DEPARTMENT_DATA
                ]
            )
            session.add_all(
                [
                    SupplyRequestDirection(
                        tenant_id="eclair",
                        code=code,
                        name=name,
                        display_order=display_order,
                    )
                    for code, name, display_order in DIRECTION_DATA
                ]
            )

        with self.session_factory.begin() as session:
            departments = list(session.scalars(
                select(Department).order_by(Department.display_order)
            ).all())
            employee = Employee(
                tenant_id="eclair",
                linked_user_id=2,
                full_name="Администратор",
                birth_date=date(1990, 1, 1),
                phone="1",
                residence_address="x",
            )
            session.add(employee)
            session.flush()
            session.add(EmployeeRoleAssignment(
                tenant_id="eclair",
                employee_id=employee.id,
                role=EmployeeRole.ADMIN,
                valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                reason="Тестовый администратор",
                assigned_by_user_id=2,
            ))
            session.add_all([
                EmployeeDepartmentAssignment(
                    tenant_id="eclair",
                    employee_id=employee.id,
                    department_id=department.id,
                    is_primary=index == 0,
                    valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    reason="Тестовый scope",
                    assigned_by_user_id=2,
                )
                for index, department in enumerate(departments)
            ])
            seller = Employee(
                tenant_id="eclair",
                linked_user_id=3,
                full_name="Продавец",
                birth_date=date(1991, 1, 1),
                phone="2",
                residence_address="y",
            )
            session.add(seller)
            session.flush()
            session.add_all([
                EmployeeRoleAssignment(
                    tenant_id="eclair",
                    employee_id=seller.id,
                    role=EmployeeRole.SELLER,
                    valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    reason="Тестовый продавец",
                    assigned_by_user_id=2,
                ),
                EmployeeDepartmentAssignment(
                    tenant_id="eclair",
                    employee_id=seller.id,
                    department_id=departments[0].id,
                    is_primary=True,
                    valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    reason="Основная точка",
                    assigned_by_user_id=2,
                ),
            ])
        self.current_user_id = 2
        self.cycle_counter = 0

        def override_get_db():
            with self.session_factory() as session:
                yield session

        def override_current_user():
            with self.session_factory() as session:
                return session.get(User, self.current_user_id)

        self.override_current_user = override_current_user
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        settings.default_tenant_id = self.previous_tenant_id
        self.engine.dispose()

    def reference_ids(self) -> tuple[str, str]:
        departments = self.client.get("/supply/departments").json()
        directions = self.client.get("/supply/request-directions").json()
        return departments[0]["id"], directions[0]["id"]

    def payload(self, **changes) -> dict:
        department_id, direction_id = self.reference_ids()
        requested_direction_id = changes.get("direction_id", direction_id)
        with self.session_factory() as session:
            requested_direction_exists = session.get(
                SupplyRequestDirection,
                UUID(requested_direction_id),
            )
        cycle_id = self.create_cycle(
            requested_direction_id
            if requested_direction_exists is not None
            else direction_id
        )
        body = {
            "department_id": department_id,
            "direction_id": direction_id,
            "cycle_id": cycle_id,
            "need_date": "2026-09-16",
            "raw_input": "Молоко 10 л\nСахар 5 кг",
            "lines": [
                {"raw_text": "Молоко 10 л"},
                {"raw_text": "Сахар 5 кг"},
            ],
        }
        body.update(changes)
        return body

    def create_cycle(self, direction_id: str) -> str:
        self.cycle_counter += 1
        with self.session_factory.begin() as session:
            cycle = SupplyRequestCycle(
                tenant_id="eclair",
                direction_id=UUID(direction_id),
                cycle_date=date(2026, 1, 1)
                + timedelta(days=self.cycle_counter),
                opens_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                closes_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
                status="OPEN",
            )
            session.add(cycle)
            session.flush()
            return str(cycle.id)

    def create_request(self, **changes) -> dict:
        response = self.client.post(
            "/supply/requests",
            json=self.payload(**changes),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_departments_are_exact_ordered_and_keep_scripts(self) -> None:
        response = self.client.get("/supply/departments")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            [(item["code"], item["name"], item["display_order"]) for item in body],
            list(DEPARTMENT_DATA),
        )
        codes = {item["code"] for item in body}
        self.assertTrue({"М15", "М35", "И25", "ЦЕХ"} <= codes)
        self.assertIn("ATO", codes)
        self.assertTrue(all(char.isascii() for char in "ATO"))
        self.assertTrue(any(not char.isascii() for char in "М15М35И25ЦЕХ"))
        self.assertTrue(
            codes.isdisjoint({"KITCHEN", "WORKSHOP_GH", "BAR_GH", "СКЛ"})
        )

    def test_directions_are_exact_and_available_to_each_department(self) -> None:
        response = self.client.get("/supply/request-directions")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [
                (item["code"], item["name"], item["display_order"])
                for item in response.json()
            ],
            list(DIRECTION_DATA),
        )

        departments = self.client.get("/supply/departments").json()
        directions = response.json()
        for department in departments:
            for direction in directions:
                created = self.client.post(
                    "/supply/requests",
                    json=self.payload(
                        department_id=department["id"],
                        direction_id=direction["id"],
                    ),
                )
                self.assertEqual(created.status_code, 201, created.text)

    def test_reference_reads_require_authentication(self) -> None:
        app.dependency_overrides.pop(get_current_user)
        departments = self.client.get("/supply/departments")
        directions = self.client.get("/supply/request-directions")
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.assertEqual(departments.status_code, 401)
        self.assertEqual(directions.status_code, 401)

    def test_department_code_is_unique_per_tenant_in_database(self) -> None:
        with self.assertRaises(IntegrityError):
            with self.session_factory.begin() as session:
                session.add(
                    Department(
                        tenant_id="eclair",
                        code="М15",
                        name="Дубликат",
                    )
                )

    def test_direction_code_is_unique_per_tenant_in_database(self) -> None:
        with self.assertRaises(IntegrityError):
            with self.session_factory.begin() as session:
                session.add(
                    SupplyRequestDirection(
                        tenant_id="eclair",
                        code="MAIN",
                        name="Дубликат",
                    )
                )

    def test_admin_creates_draft_with_backend_fields_and_ordered_lines(self) -> None:
        body = self.create_request()
        UUID(body["id"])
        self.assertEqual(body["created_by_user_id"], 2)
        self.assertEqual(body["status"], "DRAFT")
        self.assertEqual(body["source_type"], "INTERNAL")
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["need_date"], "2026-09-16")
        self.assertEqual(body["raw_input"], "Молоко 10 л\nСахар 5 кг")
        self.assertEqual(
            [(line["position"], line["raw_text"]) for line in body["lines"]],
            [(1, "Молоко 10 л"), (2, "Сахар 5 кг")],
        )
        self.assertRegex(
            body["public_number"],
            r"^ЗАЯВКА-\d{8}-М15-MAIN-001$",
        )
        with self.session_factory() as session:
            stored = session.get(SupplyRequest, UUID(body["id"]))
            self.assertEqual(stored.tenant_id, "eclair")
            self.assertEqual(stored.created_by_user_id, 2)
            stored.created_by_user_id = 999
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_two_requests_receive_distinct_sequential_numbers(self) -> None:
        first = self.create_request()
        second = self.create_request()
        self.assertNotEqual(first["public_number"], second["public_number"])
        self.assertTrue(first["public_number"].endswith("-001"))
        self.assertTrue(second["public_number"].endswith("-002"))

    def test_public_number_unique_conflict_is_retried(self) -> None:
        existing = self.create_request()
        department_id, direction_id = self.reference_ids()
        payload = SupplyRequestCreate.model_validate(
            self.payload(
                department_id=department_id,
                direction_id=direction_id,
            )
        )
        retry_number = existing["public_number"][:-3] + "002"
        with (
            self.session_factory() as session,
            patch(
                "app.supply.service._next_public_number",
                side_effect=[existing["public_number"], retry_number],
            ),
        ):
            created = create_supply_request(
                session,
                payload,
                created_by_user_id=2,
            )
        self.assertEqual(created.public_number, retry_number)

    def test_public_number_uses_business_date_at_utc_boundary(self) -> None:
        department_id, direction_id = self.reference_ids()
        payload = SupplyRequestCreate.model_validate(
            self.payload(
                department_id=department_id,
                direction_id=direction_id,
            )
        )
        with self.session_factory() as session:
            created = create_supply_request(
                session,
                payload,
                created_by_user_id=2,
                now=datetime(2026, 7, 26, 20, 30, tzinfo=timezone.utc),
            )
        self.assertRegex(
            created.public_number,
            r"^ЗАЯВКА-20260727-М15-MAIN-001$",
        )

    def test_internal_source_work_request_uses_integer_foreign_key(self) -> None:
        with self.session_factory.begin() as session:
            work_request = WorkRequest(
                request_type="warehouse",
                department="М15",
                description="Источниковая заявка",
                status="new",
                warehouse_category="products",
                created_by_user_id=2,
            )
            session.add(work_request)
            session.flush()
            work_request_id = work_request.id

        payload = SupplyRequestCreate.model_validate(self.payload())
        with self.session_factory() as session:
            created = create_supply_request(
                session,
                payload,
                created_by_user_id=2,
                source_work_request_id=work_request_id,
            )
        self.assertEqual(created.source_work_request_id, work_request_id)

        with self.session_factory() as session:
            with self.assertRaises(IntegrityError):
                create_supply_request(
                    session,
                    SupplyRequestCreate.model_validate(self.payload()),
                    created_by_user_id=2,
                    source_work_request_id=999_999,
                )

    def test_client_cannot_set_backend_owned_fields(self) -> None:
        for field, value in (
            ("tenant_id", "other"),
            ("public_number", "ATTACKER-001"),
            ("status", "SUBMITTED"),
            ("version", 9),
            ("created_by_user_id", str(uuid4())),
            ("source_work_request_id", 1),
            ("source_type", "PUBLIC_FORM"),
        ):
            response = self.client.post(
                "/supply/requests",
                json={**self.payload(), field: value},
            )
            self.assertEqual(response.status_code, 422, field)

    def test_creation_requires_admin_and_authentication(self) -> None:
        payload = self.payload()
        self.current_user_id = 1
        forbidden = self.client.post(
            "/supply/requests",
            json=payload,
        )
        app.dependency_overrides.pop(get_current_user)
        unauthorized = self.client.post(
            "/supply/requests",
            json=payload,
        )
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(unauthorized.status_code, 401)

    def test_rejects_empty_or_excessive_lines_and_blank_text(self) -> None:
        cases = (
            {"lines": []},
            {"lines": [{"raw_text": ""}]},
            {"lines": [{"raw_text": "   "}]},
            {"lines": [{"raw_text": "x" * 1001}]},
            {"lines": [{"raw_text": "x"}] * 201},
            {"raw_input": "   "},
            {"raw_input": "x" * 20_001},
        )
        for changes in cases:
            response = self.client.post(
                "/supply/requests",
                json=self.payload(**changes),
            )
            self.assertEqual(response.status_code, 422, changes.keys())

    def test_rejects_unknown_and_inactive_references(self) -> None:
        unknown_department = self.client.post(
            "/supply/requests",
            json=self.payload(department_id=str(uuid4())),
        )
        unknown_direction = self.client.post(
            "/supply/requests",
            json=self.payload(direction_id=str(uuid4())),
        )
        with self.session_factory.begin() as session:
            department = session.scalar(
                select(Department).where(Department.code == "М15")
            )
            direction = session.scalar(
                select(SupplyRequestDirection).where(
                    SupplyRequestDirection.code == "MAIN"
                )
            )
            department.is_active = False
            direction.is_active = False

        inactive_department = self.client.post(
            "/supply/requests",
            json=self.payload(department_id=str(department.id)),
        )
        inactive_direction = self.client.post(
            "/supply/requests",
            json=self.payload(
                department_id=self.client.get("/supply/departments").json()[1][
                    "id"
                ],
                direction_id=str(direction.id),
            ),
        )
        self.assertEqual(unknown_department.status_code, 400)
        self.assertEqual(unknown_direction.status_code, 400)
        self.assertEqual(inactive_department.status_code, 400)
        self.assertEqual(inactive_direction.status_code, 400)

    def test_line_failure_rolls_back_request_and_all_lines(self) -> None:
        department_id, direction_id = self.reference_ids()
        payload = SupplyRequestCreate.model_validate(
            self.payload(
                department_id=department_id,
                direction_id=direction_id,
            )
        )
        with self.session_factory() as session:
            def fail_line_flush(current_session, _, instances):
                if any(
                    isinstance(item, SupplyRequestLine)
                    for item in current_session.new
                ):
                    raise RuntimeError("line insert failed")

            event.listen(session, "before_flush", fail_line_flush)
            with self.assertRaisesRegex(RuntimeError, "line insert failed"):
                create_supply_request(
                    session,
                    payload,
                    created_by_user_id=2,
                )
            event.remove(session, "before_flush", fail_line_flush)

        with self.session_factory() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(SupplyRequest)),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(SupplyRequestLine)
                ),
                0,
            )

    def test_submit_is_one_way_sets_time_and_preserves_source(self) -> None:
        created = self.create_request()
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": 1},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        body = submitted.json()
        self.assertEqual(body["status"], "SUBMITTED")
        self.assertEqual(body["version"], 2)
        self.assertIsNotNone(body["submitted_at"])
        self.assertEqual(body["raw_input"], created["raw_input"])
        self.assertEqual(body["lines"], created["lines"])

        repeated = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": 2},
        )
        missing = self.client.post(
            f"/supply/requests/{uuid4()}/submit",
            json={"expected_version": 1},
        )
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(missing.status_code, 404)
        with self.session_factory() as session:
            events = list(session.scalars(select(AuditEvent).where(
                AuditEvent.entity_type == "SupplyRequest",
                AuditEvent.entity_id == created["id"],
            ).order_by(AuditEvent.occurred_at, AuditEvent.event_type)).all())
            self.assertEqual(
                {item.event_type for item in events},
                {"SUPPLY_REQUEST_CREATED", "SUPPLY_REQUEST_SUBMITTED"},
            )
            submitted_audit = next(
                item for item in events
                if item.event_type == "SUPPLY_REQUEST_SUBMITTED"
            )
            self.assertEqual(submitted_audit.before["status"], "DRAFT")
            self.assertEqual(submitted_audit.after["status"], "SUBMITTED")

    def test_seller_create_audit_uses_shift_context_and_scoped_history(self) -> None:
        departments = self.client.get("/supply/departments").json()
        primary = next(item for item in departments if item["code"] == "М15")
        actual = next(item for item in departments if item["code"] == "М35")
        payload = self.payload(department_id=actual["id"])
        with self.session_factory.begin() as session:
            seller_id = session.scalar(select(Employee.id).where(Employee.linked_user_id == 3))
            shift = EmployeeIikoShift(
                tenant_id="eclair", employee_id=seller_id,
                iiko_user_id="seller-iiko", external_shift_id="seller-shift",
                iiko_department_id="iiko-m35", department_id=UUID(actual["id"]),
                opened_at=datetime.now(timezone.utc) - timedelta(hours=1),
                status="OPEN", reconciliation_key="seller-shift",
                first_seen_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
            )
            session.add(shift)
            session.flush()
            shift_id = shift.id
        self.current_user_id = 3
        seller_payload = {"raw_input": "Молоко — 10 л"}
        created = self.client.put("/supply/seller/request", json=seller_payload)
        self.assertEqual(created.status_code, 200, created.text)
        with self.session_factory() as session:
            self.assertEqual(session.get(SupplyRequest, UUID(created.json()["id"])).department_id, UUID(actual["id"]))

        spoofed = self.client.put("/supply/seller/request", json={**seller_payload, "department_id": primary["id"]})
        self.assertEqual(spoofed.status_code, 409, spoofed.text)
        self.assertEqual(self.client.get("/supply/seller/window").json()["request"]["id"], created.json()["id"])

        history = self.client.get(f"/supply/requests/{created.json()['id']}/history")
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual([item["operation"] for item in history.json()], ["CREATE"])
        self.assertEqual(
            set(history.json()[0]["after"]),
            {"public_number", "need_date", "status", "line_count"},
        )
        self.assertNotIn("department_id", history.json()[0]["after"])
        self.assertEqual(self.client.get("/audit/events").status_code, 403)
        with self.session_factory() as session:
            audit = session.scalar(select(AuditEvent).where(
                AuditEvent.event_type == "SUPPLY_REQUEST_CREATED",
                AuditEvent.entity_id == created.json()["id"],
            ))
            self.assertEqual(audit.authorized_as, "SELLER")
            self.assertEqual(str(audit.primary_department_id), primary["id"])
            self.assertEqual(str(audit.actual_department_id), actual["id"])
            self.assertEqual(audit.shift_id, shift_id)
            self.assertFalse(audit.shift_context_snapshot["substitution_confirmed"])

    def test_seller_window_requires_point_selection_without_shift(self) -> None:
        self.current_user_id = 3
        closed = self.client.get("/supply/seller/window")
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertFalse(closed.json()["is_open"])
        self.current_user_id = 2
        _, direction_id = self.reference_ids()
        cycle_id = self.create_cycle(direction_id)
        with self.session_factory.begin() as session:
            session.add_all([
                SupplyUnit(tenant_id="eclair", code="KG", name_ru="Килограмм", short_name_ru="кг", is_active=True),
                SupplyUnit(tenant_id="eclair", code="PCS", name_ru="Штука", short_name_ru="шт", is_active=True),
                SupplyUnit(tenant_id="eclair", code="BOX", name_ru="Коробка", short_name_ru="кор", is_active=False),
                SupplyUnit(tenant_id="eclair", code="G", name_ru="Грамм", short_name_ru="г", is_active=True),
            ])
        self.current_user_id = 3
        opened = self.client.get("/supply/seller/window")
        self.assertTrue(opened.json()["is_open"])
        self.assertEqual(opened.json()["supported_units"], ["кг", "шт"])
        self.assertFalse(opened.json()["can_write"])
        self.assertEqual(opened.json()["allowed_actions"], ["CREATE"])
        self.assertEqual(len(opened.json()["allowed_departments"]), 3)
        self.assertEqual(opened.json()["cycle_id"], cycle_id)
        self.assertEqual(opened.json()["need_date"], "2026-01-03")
        denied = self.client.put("/supply/seller/request", json={"raw_input": "Молоко — 10 л"})
        self.assertEqual(denied.status_code, 403, denied.text)
        with self.session_factory.begin() as session:
            session.get(SupplyRequestCycle, UUID(cycle_id)).status = "CLOSED"
        closed_again = self.client.get("/supply/seller/window")
        self.assertFalse(closed_again.json()["is_open"])
        self.assertEqual(closed_again.json()["allowed_actions"], [])

    def test_seller_reconfirms_same_request_and_close_makes_it_read_only(self) -> None:
        self.current_user_id = 2
        _, direction_id = self.reference_ids()
        cycle_id = self.create_cycle(direction_id)
        with self.session_factory.begin() as session:
            seller_id = session.scalar(select(Employee.id).where(Employee.linked_user_id == 3))
            primary_id = session.scalar(select(Department.id).where(Department.code == "М15"))
            session.add(EmployeeIikoShift(
                tenant_id="eclair", employee_id=seller_id,
                iiko_user_id="seller-iiko", external_shift_id="shift-reconfirm",
                iiko_department_id="iiko-m15", department_id=primary_id,
                opened_at=datetime.now(timezone.utc) - timedelta(hours=1),
                status="OPEN", reconciliation_key="shift-reconfirm",
                first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
            ))
        self.current_user_id = 3
        window = self.client.get("/supply/seller/window").json()
        self.assertTrue(window["can_write"])
        self.assertEqual(window["department"]["id"], str(primary_id))
        first = self.client.put("/supply/seller/request", json={"raw_input": "Молоко — 10 л"})
        self.assertEqual(first.status_code, 200, first.text)
        confirmed = self.client.post("/supply/seller/request/confirm", json={"expected_version": first.json()["version"]})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        edited = self.client.put("/supply/seller/request", json={
            "raw_input": "Молоко — 12 л", "expected_version": confirmed.json()["version"],
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["id"], first.json()["id"])
        latest = self.client.post("/supply/seller/request/confirm", json={"expected_version": edited.json()["version"]})
        self.assertEqual(latest.status_code, 200, latest.text)
        self.assertEqual(latest.json()["id"], first.json()["id"])
        self.assertEqual(latest.json()["raw_input"], "Молоко — 12 л")
        with self.session_factory.begin() as session:
            session.get(SupplyRequestCycle, UUID(cycle_id)).status = "CLOSED"
        denied = self.client.put("/supply/seller/request", json={
            "raw_input": "Молоко — 20 л", "expected_version": latest.json()["version"],
        })
        self.assertEqual(denied.status_code, 409, denied.text)
        with self.session_factory() as session:
            requests = session.scalars(select(SupplyRequest).where(SupplyRequest.created_by_user_id == 3)).all()
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].raw_input, "Молоко — 12 л")

    def seller_version_window(self):
        department_id, direction_id = self.reference_ids()
        cycle_id = self.create_cycle(direction_id)
        self.current_user_id = 3
        return department_id, cycle_id

    def seller_save(self, department_id, text, version=None):
        response = self.client.put('/supply/seller/request', json={
            'department_id': department_id, 'raw_input': text, 'expected_version': version,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def seller_confirm(self, department_id, version):
        response = self.client.post('/supply/seller/request/confirm', json={
            'department_id': department_id, 'expected_version': version,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def expire_seller_window(self, cycle_id):
        now = datetime.now(timezone.utc)
        with self.session_factory.begin() as session:
            cycle = session.get(SupplyRequestCycle, UUID(cycle_id))
            cycle.closes_at = now - timedelta(minutes=1)
        return SupplyAutomationContext(execution_id=uuid4(), tenant_id='eclair',
                                       requested_at=now, executed_at=now)

    def close_seller_window(self, context):
        with self.session_factory.begin() as session:
            return close_expired_request_cycles(session, context, {'timezone': 'Asia/Yekaterinburg'})

    def test_seller_confirm_a_draft_b_close_preserves_a_and_line_identity(self):
        department, cycle = self.seller_version_window()
        draft = self.seller_save(department, 'Молоко — 10 л')
        confirmed = self.seller_confirm(department, draft['version'])
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(draft['id']))
            line_ids = [line.id for line in item.lines]
            confirmed_at = item.submitted_at
        edited = self.seller_save(department, 'Молоко — 12 л', confirmed['version'])
        self.assertEqual(edited['status'], 'DRAFT')
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(draft['id']))
            self.assertEqual(item.raw_input, 'Молоко — 10 л')
            self.assertEqual(item.status, 'SUBMITTED')
            self.assertEqual(item.submitted_at, confirmed_at)
            self.assertEqual([line.id for line in item.lines], line_ids)
            self.assertEqual(item.seller_confirmed_snapshot['version'], confirmed['version'])
        context = self.expire_seller_window(cycle)
        # Even while the scheduler is pending, re-entry cannot present B as confirmed.
        pending_close = self.client.get('/supply/seller/window').json()
        self.assertFalse(pending_close['can_write'])
        self.assertEqual(pending_close['request']['raw_input'], 'Молоко — 10 л')
        self.assertEqual(self.close_seller_window(context)['closed_count'], 1)
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(draft['id']))
            self.assertEqual(item.raw_input, 'Молоко — 10 л')
            self.assertEqual(item.status, 'SUBMITTED')
            self.assertEqual([line.id for line in item.lines], line_ids)
            self.assertIsNone(item.seller_draft_input)
            self.assertIsNotNone(item.seller_finalized_at)
            events = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == draft['id'])).all()
            self.assertIn('SUPPLY_REQUEST_SELLER_EDITED', [event.event_type for event in events])
            self.assertIn('SUPPLY_REQUEST_SELLER_CONFIRMED', [event.event_type for event in events])
            finalized = next(event for event in events if event.event_type == 'SUPPLY_REQUEST_SELLER_FINALIZED')
            self.assertEqual(finalized.source, 'SYSTEM')
            self.assertIsNone(finalized.actor_user_id)
            self.assertEqual(finalized.after['confirmed_version'], confirmed['version'])
            self.assertTrue(finalized.after['draft_discarded'])
            self.assertEqual(finalized.correlation_id, str(context.execution_id))
        closed = self.client.get('/supply/seller/window').json()
        self.assertEqual(closed['request']['raw_input'], 'Молоко — 10 л')
        self.assertEqual(closed['request']['status'], 'SUBMITTED')

    def test_seller_confirm_b_close_finalizes_b(self):
        department, cycle = self.seller_version_window()
        draft = self.seller_save(department, 'Молоко — 10 л')
        a = self.seller_confirm(department, draft['version'])
        edit = self.seller_save(department, 'Молоко — 12 л', a['version'])
        b = self.seller_confirm(department, edit['version'])
        self.assertEqual(b['id'], a['id'])
        self.close_seller_window(self.expire_seller_window(cycle))
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(draft['id']))
            self.assertEqual(item.raw_input, 'Молоко — 12 л')
            self.assertEqual([line.raw_text for line in item.lines], ['Молоко — 12 л'])
            self.assertEqual(item.seller_confirmed_snapshot['version'], b['version'])
            self.assertEqual(item.seller_confirmed_snapshot['raw_input'], item.raw_input)

    def test_seller_repeated_edits_confirms_and_reentry_return_current_draft(self):
        department, cycle = self.seller_version_window()
        state = self.seller_save(department, 'Молоко — 10 л')
        state = self.seller_confirm(department, state['version'])
        request_id = state['id']
        for amount in (12, 13, 14):
            state = self.seller_save(department, f'Молоко — {amount} л', state['version'])
            reopened = self.client.get('/supply/seller/window').json()['request']
            self.assertEqual(reopened, state)
            self.assertEqual(reopened['status'], 'DRAFT')
            state = self.seller_confirm(department, state['version'])
            self.assertEqual(state['id'], request_id)
            self.assertEqual(self.client.get('/supply/seller/window').json()['request'], state)
        state = self.seller_save(department, 'Молоко — 99 л', state['version'])
        state = self.seller_save(department, 'Молоко — 100 л', state['version'])
        self.close_seller_window(self.expire_seller_window(cycle))
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(request_id))
            self.assertEqual(item.raw_input, 'Молоко — 14 л')
            self.assertEqual(session.scalar(select(func.count()).select_from(SupplyRequest)), 1)

    def test_seller_scheduler_close_is_idempotent(self):
        department, cycle = self.seller_version_window()
        draft = self.seller_save(department, 'Молоко — 10 л')
        confirmed = self.seller_confirm(department, draft['version'])
        self.seller_save(department, 'Молоко — 12 л', confirmed['version'])
        context = self.expire_seller_window(cycle)
        self.assertEqual(self.close_seller_window(context)['closed_count'], 1)
        with self.session_factory() as session:
            first = session.get(SupplyRequest, UUID(draft['id']))
            version, finalized_at = first.version, first.seller_finalized_at
        self.assertEqual(self.close_seller_window(context)['closed_count'], 0)
        with self.session_factory() as session:
            second = session.get(SupplyRequest, UUID(draft['id']))
            self.assertEqual((second.version, second.seller_finalized_at), (version, finalized_at))
            self.assertEqual(session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.event_type == 'SUPPLY_REQUEST_SELLER_FINALIZED')), 1)

    def test_seller_never_confirmed_draft_remains_draft_on_close(self):
        department, cycle = self.seller_version_window()
        draft = self.seller_save(department, 'Молоко — 10 л')
        edit = self.seller_save(department, 'Молоко — 12 л', draft['version'])
        self.close_seller_window(self.expire_seller_window(cycle))
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(draft['id']))
            self.assertEqual((item.status, item.raw_input, item.version), ('DRAFT', 'Молоко — 12 л', edit['version']))
            self.assertIsNone(item.submitted_at)
            self.assertIsNone(item.seller_confirmed_snapshot)
            self.assertIsNone(item.seller_finalized_at)

    def test_seller_confirm_audit_failure_rolls_back_payload_and_snapshot(self):
        department, _ = self.seller_version_window()
        draft = self.seller_save(department, 'Молоко — 10 л')
        confirmed = self.seller_confirm(department, draft['version'])
        edited = self.seller_save(department, 'Молоко — 12 л', confirmed['version'])
        with patch('app.supply.seller_requests.record_audit_event', side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):
                self.client.post('/supply/seller/request/confirm', json={
                    'department_id': department, 'expected_version': edited['version'],
                })
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(draft['id']))
            self.assertEqual(item.raw_input, 'Молоко — 10 л')
            self.assertEqual(item.seller_draft_input, 'Молоко — 12 л')
            self.assertEqual(item.seller_confirmed_snapshot['version'], confirmed['version'])
            self.assertEqual(item.version, edited['version'])
        retry = self.seller_confirm(department, edited['version'])
        self.assertEqual(retry['raw_input'], 'Молоко — 12 л')

    def test_seller_close_audit_failure_rolls_back_cycle_and_finalization(self):
        department, cycle = self.seller_version_window()
        draft = self.seller_save(department, 'Молоко — 10 л')
        confirmed = self.seller_confirm(department, draft['version'])
        self.seller_save(department, 'Молоко — 12 л', confirmed['version'])
        context = self.expire_seller_window(cycle)
        with patch('app.supply.seller_versions.record_audit_event', side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):
                self.close_seller_window(context)
        with self.session_factory() as session:
            self.assertEqual(session.get(SupplyRequestCycle, UUID(cycle)).status, 'OPEN')
            item = session.get(SupplyRequest, UUID(draft['id']))
            self.assertIsNone(item.seller_finalized_at)
            self.assertEqual(item.seller_draft_input, 'Молоко — 12 л')
        self.assertEqual(self.close_seller_window(context)['closed_count'], 1)

    def test_seller_unresolved_shift_uses_only_configured_retail_points(self) -> None:
        self.current_user_id = 2
        _, direction_id = self.reference_ids()
        self.create_cycle(direction_id)
        with self.session_factory.begin() as session:
            seller_id = session.scalar(select(Employee.id).where(Employee.linked_user_id == 3))
            session.add(EmployeeIikoShift(
                tenant_id="eclair", employee_id=seller_id,
                iiko_user_id="seller-iiko", external_shift_id="shift-unresolved",
                iiko_department_id="unknown", department_id=None,
                opened_at=datetime.now(timezone.utc) - timedelta(hours=1),
                status="OPEN", reconciliation_key="shift-unresolved",
                first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
            ))
            chosen = session.scalar(select(Department.id).where(Department.code == "М35"))
            forbidden = session.scalar(select(Department.id).where(Department.code == "ЦЕХ"))
        self.current_user_id = 3
        window = self.client.get("/supply/seller/window").json()
        self.assertEqual(len(window["allowed_departments"]), 3)
        self.assertFalse(window["can_write"])
        denied = self.client.put("/supply/seller/request", json={"department_id": str(forbidden), "raw_input": "Молоко — 10 л"})
        self.assertEqual(denied.status_code, 403, denied.text)
        created = self.client.put("/supply/seller/request", json={"department_id": str(chosen), "raw_input": "Молоко — 10 л"})
        self.assertEqual(created.status_code, 200, created.text)
        with self.session_factory() as session:
            self.assertEqual(session.get(SupplyRequest, UUID(created.json()["id"])).department_id, chosen)

    def test_seller_without_assignment_or_shift_reopens_same_request(self) -> None:
        _, direction_id = self.reference_ids()
        cycle_id = self.create_cycle(direction_id)
        with self.session_factory.begin() as session:
            seller_id = session.scalar(select(Employee.id).where(Employee.linked_user_id == 3))
            session.query(EmployeeDepartmentAssignment).filter(
                EmployeeDepartmentAssignment.employee_id == seller_id,
            ).delete()
            retail_id = session.scalar(select(Department.id).where(Department.code == "М35"))
            other_id = session.scalar(select(Department.id).where(Department.code == "М15"))
            production_id = session.scalar(select(Department.id).where(Department.code == "ЦЕХ"))
        self.current_user_id = 3
        window = self.client.get("/supply/seller/window")
        self.assertEqual(window.status_code, 200, window.text)
        self.assertEqual(window.json()["allowed_actions"], ["CREATE"])
        self.assertIsNone(window.json()["department"])
        self.assertEqual(self.client.get("/supply/requests").status_code, 200)
        invalid = self.client.put("/supply/seller/request", json={
            "department_id": str(production_id), "raw_input": "Молоко — 10 л",
        })
        self.assertEqual(invalid.status_code, 403, invalid.text)
        created = self.client.put("/supply/seller/request", json={
            "department_id": str(retail_id), "raw_input": "Молоко — 10 л",
        })
        self.assertEqual(created.status_code, 200, created.text)
        confirmed = self.client.post("/supply/seller/request/confirm", json={
            "expected_version": created.json()["version"],
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        reopened = self.client.get("/supply/seller/window").json()
        self.assertEqual(reopened["request"]["id"], created.json()["id"])
        self.assertEqual(reopened["department"]["id"], str(retail_id))
        self.assertTrue(reopened["can_write"])
        changed_point = self.client.put("/supply/seller/request", json={
            "department_id": str(other_id), "raw_input": "Молоко — 12 л",
            "expected_version": confirmed.json()["version"],
        })
        self.assertEqual(changed_point.status_code, 409, changed_point.text)
        edited = self.client.put("/supply/seller/request", json={
            "raw_input": "Молоко — 12 л", "expected_version": confirmed.json()["version"],
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        latest = self.client.post("/supply/seller/request/confirm", json={
            "expected_version": edited.json()["version"],
        })
        self.assertEqual(latest.status_code, 200, latest.text)
        self.assertEqual(latest.json()["id"], created.json()["id"])
        self.assertEqual(len(self.client.get("/supply/requests").json()), 1)
        self.assertEqual(self.client.get(f"/supply/requests/{created.json()['id']}").status_code, 200)
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(created.json()["id"]))
            self.assertEqual(item.cycle_id, UUID(cycle_id))
            self.assertEqual(item.direction_id, UUID(direction_id))
            self.assertEqual(item.need_date, date(2026, 1, 3))
            self.assertIsNone(item.creator_shift_id)
            self.assertEqual(item.creator_authorized_as, "SELLER")
        with self.session_factory.begin() as session:
            session.get(SupplyRequestCycle, UUID(cycle_id)).status = "CLOSED"
        self.assertEqual(self.client.get("/supply/seller/window").json()["allowed_actions"], [])
        denied = self.client.put("/supply/seller/request", json={
            "raw_input": "Молоко — 20 л", "expected_version": latest.json()["version"],
        })
        self.assertEqual(denied.status_code, 409, denied.text)

    def test_admin_uses_the_current_window_flow(self) -> None:
        department_id, direction_id = self.reference_ids()
        cycle_id = self.create_cycle(direction_id)
        window = self.client.get("/supply/seller/window")
        self.assertEqual(window.status_code, 200, window.text)
        self.assertEqual(window.json()["allowed_actions"], ["CREATE"])
        created = self.client.put("/supply/seller/request", json={
            "department_id": department_id, "raw_input": "Молоко — 10 л",
        })
        self.assertEqual(created.status_code, 200, created.text)
        confirmed = self.client.post("/supply/seller/request/confirm", json={
            "department_id": department_id, "expected_version": created.json()["version"],
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        reopened = self.client.get("/supply/seller/window", params={"department_id": department_id})
        self.assertEqual(reopened.json()["request"]["id"], created.json()["id"])
        with self.session_factory() as session:
            item = session.get(SupplyRequest, UUID(created.json()["id"]))
            self.assertEqual(item.cycle_id, UUID(cycle_id))
            self.assertEqual(item.direction_id, UUID(direction_id))
            self.assertEqual(item.need_date, date(2026, 1, 3))
            self.assertEqual(item.creator_authorized_as, "ADMIN")

    def test_cancel_creates_meaningful_audit_with_reason(self) -> None:
        created = self.create_request()
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": 1},
        )
        cancelled = self.client.post(
            f"/supply/requests/{created['id']}/cancel",
            json={"expected_version": submitted.json()["version"], "reason": "Точка отменила заявку"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        with self.session_factory() as session:
            audit = session.scalar(select(AuditEvent).where(
                AuditEvent.event_type == "SUPPLY_REQUEST_CANCELLED",
                AuditEvent.entity_id == created["id"],
            ))
            self.assertEqual(audit.reason, "Точка отменила заявку")
            self.assertEqual(audit.before["status"], "SUBMITTED")
            self.assertEqual(audit.after["status"], "CANCELLED")

    def test_list_and_card_are_ordered_protected_and_tenant_scoped(self) -> None:
        created = self.create_request()
        self.current_user_id = 1
        self.assertEqual(self.client.get("/supply/requests").status_code, 403)
        self.current_user_id = 2
        listed = self.client.get("/supply/requests")
        detail = self.client.get(f"/supply/requests/{created['id']}")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["id"], created["id"])
        self.assertEqual(listed.json()[0]["line_count"], 2)
        self.assertEqual(listed.headers["x-total-count"], "1")
        self.assertIn("no-store", listed.headers["cache-control"])
        self.assertEqual(
            [line["position"] for line in detail.json()["lines"]],
            [1, 2],
                )

        with self.session_factory.begin() as session:
            session.add(User(
                id=4,
                username="other-viewer",
                display_name="Другой tenant",
                hashed_password="unused",
                is_active=True,
                is_admin=False,
                can_view_requests=True,
                tenant_id="other",
            ))
            other_department = Department(
                tenant_id="other",
                code="OTHER",
                name="Другой tenant",
            )
            other_direction = SupplyRequestDirection(
                tenant_id="other",
                code="MAIN",
                name="Основной",
            )
            session.add_all([other_department, other_direction])
            session.flush()
            other = SupplyRequest(
                tenant_id="other",
                public_number="ЗАЯВКА-20260727-OTHER-MAIN-001",
                department_id=other_department.id,
                direction_id=other_direction.id,
                status="DRAFT",
                source_type="INTERNAL",
                raw_input="Скрытая заявка",
            )
            other.lines = [SupplyRequestLine(
                tenant_id="other", position=1, raw_text="Скрыто"
            )]
            session.add(other)
            session.flush()
            other_id = other.id

        self.current_user_id = 4
        other_list = self.client.get("/supply/requests")
        self.assertEqual(other_list.status_code, 403, other_list.text)
        self.assertEqual(
            self.client.get(f"/supply/requests/{created['id']}").status_code,
            404,
        )

        self.current_user_id = 1

        self.assertEqual(self.client.get("/supply/requests").status_code, 403)
        self.assertEqual(
            self.client.get(f"/supply/requests/{other_id}").status_code,
            404,
        )

        for method, path, payload in (
            (
                "post",
                f"/supply/requests/{created['id']}/recognize",
                {"expected_version": created["version"]},
            ),
            (
                "post",
                f"/supply/requests/{created['id']}/plan",
                {"expected_version": created["version"], "simple_mode": True},
            ),
            (
                "post",
                f"/supply/requests/{created['id']}/cancel",
                {"expected_version": created["version"], "reason": "Нет"},
            ),
        ):
            response = getattr(self.client, method)(path, json=payload)
            self.assertEqual(response.status_code, 403, response.text)

        self.current_user_id = 2
        self.assertEqual(
            self.client.get(f"/supply/requests/{created['id']}").status_code,
            200,
        )

        app.dependency_overrides.pop(get_current_user)
        unauthorized_list = self.client.get("/supply/requests")
        unauthorized_detail = self.client.get(
            f"/supply/requests/{created['id']}"
        )
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.assertEqual(unauthorized_list.status_code, 401)
        self.assertEqual(unauthorized_detail.status_code, 401)

    def test_request_registry_page_size_is_fixed_at_twenty_five(self) -> None:
        for _ in range(26):
            self.create_request()
        first_page = self.client.get(
            "/supply/requests",
            params={"limit": 100, "offset": 0},
        )
        second_page = self.client.get(
            "/supply/requests",
            params={"limit": 1, "offset": 25},
        )
        self.assertEqual(first_page.status_code, 200, first_page.text)
        self.assertEqual(len(first_page.json()), 25)
        self.assertEqual(first_page.headers["x-total-count"], "26")
        self.assertEqual(len(second_page.json()), 1)
        self.assertEqual(second_page.headers["x-total-count"], "26")

    def test_seller_reads_own_and_primary_department_requests_without_shift(self) -> None:
        departments = self.client.get("/supply/departments").json()
        primary = next(item for item in departments if item["code"] == "М15")
        other = next(item for item in departments if item["code"] == "М35")
        hidden = next(item for item in departments if item["code"] == "ЦЕХ")
        primary_request = self.create_request(department_id=primary["id"])
        own_request = self.create_request(department_id=other["id"])
        hidden_request = self.create_request(department_id=hidden["id"])
        with self.session_factory.begin() as session:
            session.get(SupplyRequest, UUID(own_request["id"])).created_by_user_id = 3

        self.current_user_id = 3
        response = self.client.get("/supply/requests")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            {item["id"] for item in response.json()},
            {primary_request["id"], own_request["id"]},
        )
        self.assertEqual(
            self.client.get(f"/supply/requests/{hidden_request['id']}").status_code,
            403,
        )

    def test_public_number_shape_supports_cyrillic_department(self) -> None:
        department = next(
            item
            for item in self.client.get("/supply/departments").json()
            if item["code"] == "ЦЕХ"
        )
        direction = next(
            item
            for item in self.client.get("/supply/request-directions").json()
            if item["code"] == "HOUSEHOLD"
        )
        body = self.create_request(
            department_id=department["id"],
            direction_id=direction["id"],
        )
        self.assertTrue(
            re.fullmatch(
                r"ЗАЯВКА-\d{8}-ЦЕХ-HOUSEHOLD-001",
                body["public_number"],
            )
        )


if __name__ == "__main__":
    unittest.main()
