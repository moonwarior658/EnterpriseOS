import os
import unittest
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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
    SupplyDepartmentProductMapping,
    SupplyDepartmentProductCorrection,
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
from app.models.work_request import WorkRequest
from app.supply.normalization import normalize_product_text


class SupplyCyclesAndDuplicatesApiTests(unittest.TestCase):
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
        for table in (
            User.__table__,
            Department.__table__,
            SupplyRequestDirection.__table__,
            SupplyRequestCycle.__table__,
            SupplyUnit.__table__,
            SupplyProductCategory.__table__,
            SupplyStorageZone.__table__,
            SupplyProduct.__table__,
            SupplyProductAlias.__table__,
            SupplyDepartmentProductMapping.__table__,
            WorkRequest.__table__,
            SupplyRequest.__table__,
            SupplyRequestLine.__table__,
            SupplyDepartmentProductCorrection.__table__,
            SupplyDepartmentProductMappingAuditEvent.__table__,
            SupplyLineAllocation.__table__,
            SupplyDepartmentDebt.__table__,
            SupplyDepartmentDebtEvent.__table__,
            SupplyRequestLineDebtLink.__table__,
        ):
            table.create(self.engine)
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
            self.department = Department(
                tenant_id="eclair",
                code="М15",
                name="Матросова 15",
            )
            self.main_direction = SupplyRequestDirection(
                tenant_id="eclair",
                code="MAIN",
                name="Основной",
            )
            self.household_direction = SupplyRequestDirection(
                tenant_id="eclair",
                code="HOUSEHOLD",
                name="Хозяйственный",
            )
            self.kg = SupplyUnit(
                tenant_id="eclair",
                code="KG",
                name_ru="килограмм",
                short_name_ru="кг",
                allows_fraction=True,
            )
            self.liter = SupplyUnit(
                tenant_id="eclair",
                code="L",
                name_ru="литр",
                short_name_ru="л",
                allows_fraction=True,
            )
            session.add_all(
                [
                    self.department,
                    self.main_direction,
                    self.household_direction,
                    self.kg,
                    self.liter,
                ]
            )
            session.flush()
            self.milk = SupplyProduct(
                tenant_id="eclair",
                name="Молоко",
                normalized_name=normalize_product_text("Молоко"),
                default_unit_id=self.liter.id,
                request_direction_id=self.main_direction.id,
            )
            session.add(self.milk)

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

    def cycle_payload(self, **changes) -> dict:
        self.cycle_counter += 1
        now = datetime.now(timezone.utc)
        payload = {
            "direction_id": str(self.main_direction.id),
            "cycle_date": str(
                date(2026, 1, 1) + timedelta(days=self.cycle_counter)
            ),
            "opens_at": (now - timedelta(hours=1)).isoformat(),
            "closes_at": (now + timedelta(hours=1)).isoformat(),
            "hard_closes_at": (now + timedelta(hours=2)).isoformat(),
            "status": "OPEN",
        }
        payload.update(changes)
        return payload

    def create_cycle(self, **changes) -> dict:
        response = self.client.post(
            "/supply/request-cycles",
            json=self.cycle_payload(**changes),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def request_payload(self, cycle_id: str, *lines: str, **changes) -> dict:
        payload = {
            "department_id": str(self.department.id),
            "direction_id": str(self.main_direction.id),
            "cycle_id": cycle_id,
            "raw_input": "\n".join(lines),
            "lines": [{"raw_text": line} for line in lines],
        }
        payload.update(changes)
        return payload

    def create_request(self, cycle_id: str, *lines: str) -> dict:
        response = self.client.post(
            "/supply/requests",
            json=self.request_payload(cycle_id, *lines),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_cycle_crud_filters_validation_and_terminal_statuses(self) -> None:
        first = self.create_cycle()
        second = self.create_cycle(
            direction_id=str(self.household_direction.id),
            status="SCHEDULED",
        )
        listed = self.client.get(
            "/supply/request-cycles",
            params={
                "direction_id": str(self.household_direction.id),
                "status": "SCHEDULED",
                "date_from": second["cycle_date"],
                "date_to": second["cycle_date"],
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(listed.json()["items"][0]["id"], second["id"])
        self.assertEqual(
            self.client.get(
                f"/supply/request-cycles/{first['id']}"
            ).status_code,
            200,
        )

        invalid_window = self.client.post(
            "/supply/request-cycles",
            json=self.cycle_payload(
                opens_at="2026-01-01T10:00:00+05:00",
                closes_at="2026-01-01T09:00:00+05:00",
            ),
        )
        naive_time = self.client.post(
            "/supply/request-cycles",
            json=self.cycle_payload(
                opens_at="2026-01-01T10:00:00",
            ),
        )
        self.assertEqual(invalid_window.status_code, 422)
        self.assertEqual(naive_time.status_code, 422)

        cancelled = self.client.patch(
            f"/supply/request-cycles/{first['id']}",
            json={"status": "CANCELLED"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        reopened = self.client.patch(
            f"/supply/request-cycles/{first['id']}",
            json={"status": "OPEN"},
        )
        self.assertEqual(reopened.status_code, 409)

        duplicate = self.client.post(
            "/supply/request-cycles",
            json={
                **self.cycle_payload(),
                "direction_id": second["direction_id"],
                "cycle_date": second["cycle_date"],
            },
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_cycle_endpoints_are_admin_only_and_tenant_scoped(self) -> None:
        cycle = self.create_cycle()
        with self.session_factory.begin() as session:
            foreign_direction = SupplyRequestDirection(
                tenant_id="other",
                code="MAIN",
                name="Чужое направление",
            )
            session.add(foreign_direction)
            session.flush()
            foreign_cycle = SupplyRequestCycle(
                tenant_id="other",
                direction_id=foreign_direction.id,
                cycle_date=date(2026, 7, 27),
                opens_at=datetime.now(timezone.utc) - timedelta(hours=1),
                closes_at=datetime.now(timezone.utc) + timedelta(hours=1),
                status="OPEN",
            )
            session.add(foreign_cycle)
            session.flush()
            foreign_cycle_id = foreign_cycle.id
        self.assertEqual(
            self.client.get(
                f"/supply/request-cycles/{foreign_cycle_id}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/supply/request-cycles").json()["total"],
            1,
        )

        self.current_user_id = 1
        self.assertEqual(
            self.client.get("/supply/request-cycles").status_code,
            403,
        )
        app.dependency_overrides.pop(get_current_user)
        self.assertEqual(
            self.client.get(
                f"/supply/request-cycles/{cycle['id']}"
            ).status_code,
            401,
        )

    def test_request_cycle_rules_uniqueness_and_immutable_identity(self) -> None:
        cycle = self.create_cycle()
        created = self.create_request(cycle["id"], "Молоко 1 л")
        repeated = self.client.post(
            "/supply/requests",
            json=self.request_payload(cycle["id"], "Сахар 1 кг"),
        )
        self.assertEqual(repeated.status_code, 409, repeated.text)
        self.assertEqual(
            repeated.json()["detail"],
            {
                "code": "SUPPLY_REQUEST_ALREADY_EXISTS",
                "request_id": created["id"],
                "request_number": created["public_number"],
            },
        )
        immutable = self.client.patch(
            f"/supply/request-cycles/{cycle['id']}",
            json={"cycle_date": "2027-01-01"},
        )
        self.assertEqual(immutable.status_code, 409)

        scheduled = self.create_cycle(status="SCHEDULED")
        future = self.create_cycle(
            opens_at=(
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
            closes_at=(
                datetime.now(timezone.utc) + timedelta(hours=2)
            ).isoformat(),
            hard_closes_at=None,
        )
        wrong_direction = self.create_cycle(
            direction_id=str(self.household_direction.id)
        )
        for blocked_cycle, changes in (
            (scheduled, {}),
            (future, {}),
            (
                wrong_direction,
                {"direction_id": str(self.main_direction.id)},
            ),
        ):
            response = self.client.post(
                "/supply/requests",
                json=self.request_payload(
                    blocked_cycle["id"],
                    "Молоко 1 л",
                    **changes,
                ),
            )
            self.assertEqual(response.status_code, 409, response.text)

    def test_optimistic_locking_and_duplicate_resolution(self) -> None:
        cycle = self.create_cycle()
        created = self.create_request(
            cycle["id"],
            "Молоко 1 л",
            "Молоко 2 кг",
        )
        recognized = self.client.post(
            f"/supply/requests/{created['id']}/recognize",
            json={"expected_version": 1, "force": False},
        )
        self.assertEqual(recognized.status_code, 200, recognized.text)
        stale_recognition = self.client.post(
            f"/supply/requests/{created['id']}/recognize",
            json={"expected_version": 1, "force": False},
        )
        self.assertEqual(stale_recognition.status_code, 409)
        self.assertEqual(
            stale_recognition.json()["detail"],
            {
                "code": "SUPPLY_REQUEST_VERSION_CONFLICT",
                "current_version": 2,
                "expected_version": 1,
            },
        )

        detected = self.client.post(
            f"/supply/requests/{created['id']}/detect-duplicates",
            json={"expected_version": 2},
        )
        self.assertEqual(detected.status_code, 200, detected.text)
        detected_body = detected.json()
        self.assertEqual(detected_body["version"], 3)
        group_ids = {
            line["duplicate_group_id"] for line in detected_body["lines"]
        }
        self.assertEqual(len(group_ids), 1)
        group_id = group_ids.pop()
        self.assertIsNotNone(group_id)
        self.assertEqual(
            {line["duplicate_status"] for line in detected_body["lines"]},
            {"SUSPECTED"},
        )

        identical = self.client.post(
            f"/supply/requests/{created['id']}/detect-duplicates",
            json={"expected_version": 3},
        )
        self.assertEqual(identical.status_code, 200, identical.text)
        self.assertEqual(identical.json()["version"], 3)

        blocked_submit = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": 3},
        )
        self.assertEqual(blocked_submit.status_code, 409)
        self.assertEqual(
            blocked_submit.json()["detail"]["code"],
            "SUPPLY_REQUEST_DUPLICATES_PRESENT",
        )
        self.assertEqual(
            blocked_submit.json()["detail"]["duplicate_groups"],
            [group_id],
        )
        self.assertEqual(
            self.client.get(f"/supply/requests/{created['id']}").json()[
                "version"
            ],
            3,
        )

        resolved = self.client.post(
            f"/supply/requests/{created['id']}/duplicate-groups/"
            f"{group_id}/resolve",
            json={"expected_version": 3, "action": "KEEP_SEPARATE"},
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["version"], 4)
        self.assertEqual(
            {line["duplicate_status"] for line in resolved.json()["lines"]},
            {"RESOLVED"},
        )
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": 4},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["version"], 5)
        self.assertEqual(submitted.json()["status"], "SUBMITTED")

    def test_confirmed_and_unmatched_duplicates_block_submit(self) -> None:
        cycle = self.create_cycle()
        created = self.create_request(
            cycle["id"],
            "Неизвестный товар 1 кг",
            " неизвестный   товар 2 кг ",
        )
        recognition = self.client.post(
            f"/supply/requests/{created['id']}/recognize",
            json={"expected_version": 1},
        )
        self.assertEqual(recognition.status_code, 200, recognition.text)
        detected = self.client.post(
            f"/supply/requests/{created['id']}/detect-duplicates",
            json={"expected_version": 2},
        ).json()
        group_id = detected["lines"][0]["duplicate_group_id"]
        confirmed = self.client.post(
            f"/supply/requests/{created['id']}/duplicate-groups/"
            f"{group_id}/resolve",
            json={"expected_version": 3, "action": "MARK_CONFIRMED"},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(
            {line["duplicate_status"] for line in confirmed.json()["lines"]},
            {"CONFIRMED"},
        )
        blocked = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": 4},
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(
            blocked.json()["detail"]["code"],
            "SUPPLY_REQUEST_DUPLICATES_PRESENT",
        )

        line_id = created["lines"][0]["id"]
        stale_match = self.client.post(
            f"/supply/requests/{created['id']}/lines/{line_id}/match",
            json={"expected_version": 1, "action": "RESET"},
        )
        self.assertEqual(stale_match.status_code, 409)

    def test_database_uniqueness_and_nullable_legacy_cycle(self) -> None:
        cycle = self.create_cycle()
        self.create_request(cycle["id"], "Молоко 1 л")
        with self.assertRaises(IntegrityError):
            with self.session_factory.begin() as session:
                duplicate = SupplyRequest(
                    tenant_id="eclair",
                    public_number="ЗАЯВКА-DUPLICATE-001",
                    department_id=self.department.id,
                    direction_id=self.main_direction.id,
                    cycle_id=UUID(cycle["id"]),
                    raw_input="Дубликат",
                )
                session.add(duplicate)
                session.flush()

        with self.session_factory.begin() as session:
            legacy = SupplyRequest(
                tenant_id="eclair",
                public_number=f"ЗАЯВКА-LEGACY-{uuid4()}",
                department_id=self.department.id,
                direction_id=self.main_direction.id,
                cycle_id=None,
                raw_input="Старая строка",
            )
            session.add(legacy)
            session.flush()
            self.assertIsNone(legacy.cycle_id)


if __name__ == "__main__":
    unittest.main()
