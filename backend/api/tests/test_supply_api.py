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
    SupplyProduct,
    SupplyProductAlias,
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
from app.models.work_request import WorkRequest
from app.schemas.supply import SupplyRequestCreate
from app.supply.service import create_supply_request


DEPARTMENT_DATA = (
    ("М15", "Матросова 15", 10),
    ("М35", "Матросова 35", 20),
    ("М6А", "Маяковского 6а", 30),
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
        SupplyRequestDirection.__table__.create(self.engine)
        SupplyRequestCycle.__table__.create(self.engine)
        SupplyUnit.__table__.create(self.engine)
        SupplyProductCategory.__table__.create(self.engine)
        SupplyStorageZone.__table__.create(self.engine)
        SupplyProduct.__table__.create(self.engine)
        SupplyProductAlias.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
        SupplyRequest.__table__.create(self.engine)
        SupplyRequestLine.__table__.create(self.engine)
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
                    ),
                    User(
                        id=2,
                        username="admin",
                        display_name="Администратор",
                        hashed_password="unused",
                        is_active=True,
                        is_admin=True,
                    ),
                ]
            )
            session.add_all(
                [
                    Department(
                        tenant_id="eclair",
                        code=code,
                        name=name,
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
        self.assertTrue({"М15", "М35", "М6А", "ЦЕХ"} <= codes)
        self.assertIn("ATO", codes)
        self.assertTrue(all(char.isascii() for char in "ATO"))
        self.assertTrue(any(not char.isascii() for char in "М15М35М6АЦЕХ"))
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

    def test_list_and_card_are_ordered_protected_and_tenant_scoped(self) -> None:
        created = self.create_request()
        listed = self.client.get("/supply/requests")
        detail = self.client.get(f"/supply/requests/{created['id']}")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["id"], created["id"])
        self.assertEqual(listed.json()[0]["line_count"], 2)
        self.assertEqual(
            [line["position"] for line in detail.json()["lines"]],
            [1, 2],
        )

        with self.session_factory.begin() as session:
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
            other.lines = [SupplyRequestLine(position=1, raw_text="Скрыто")]
            session.add(other)
            session.flush()
            other_id = other.id

        self.assertEqual(
            [item["id"] for item in self.client.get("/supply/requests").json()],
            [created["id"]],
        )
        self.assertEqual(
            self.client.get(f"/supply/requests/{other_id}").status_code,
            404,
        )

        app.dependency_overrides.pop(get_current_user)
        unauthorized_list = self.client.get("/supply/requests")
        unauthorized_detail = self.client.get(
            f"/supply/requests/{created['id']}"
        )
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.assertEqual(unauthorized_list.status_code, 401)
        self.assertEqual(unauthorized_detail.status_code, 401)

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
