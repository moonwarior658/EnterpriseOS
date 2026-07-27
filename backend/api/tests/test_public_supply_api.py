import os
import unittest
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.public_supply import token_rate_guard
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
from app.supply.normalization import normalize_product_text
from app.supply.public_service import hash_public_token, hash_source_ip


class PublicSupplyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        token_rate_guard.clear()
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
            WorkRequest.__table__,
            SupplyRequest.__table__,
            SupplyRequestLine.__table__,
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
        now = datetime.now(timezone.utc)
        with self.session_factory.begin() as session:
            self.department = Department(
                tenant_id="eclair",
                code="М15",
                name="Матросова 15",
                display_order=10,
            )
            self.inactive_department = Department(
                tenant_id="eclair",
                code="OLD",
                name="Закрытое",
                is_active=False,
            )
            self.foreign_department = Department(
                tenant_id="other",
                code="FOREIGN",
                name="Чужое",
            )
            self.direction = SupplyRequestDirection(
                tenant_id="eclair",
                code="MAIN",
                name="Основной",
                display_order=10,
            )
            self.inactive_direction = SupplyRequestDirection(
                tenant_id="eclair",
                code="OLD",
                name="Неактивное",
                is_active=False,
            )
            session.add_all(
                [
                    self.department,
                    self.inactive_department,
                    self.foreign_department,
                    self.direction,
                    self.inactive_direction,
                ]
            )
            session.flush()
            self.open_cycle = SupplyRequestCycle(
                tenant_id="eclair",
                direction_id=self.direction.id,
                cycle_date=date.today(),
                opens_at=now - timedelta(hours=1),
                closes_at=now + timedelta(hours=1),
                hard_closes_at=now + timedelta(hours=2),
                status="OPEN",
            )
            session.add_all(
                [
                    self.open_cycle,
                    SupplyRequestCycle(
                        tenant_id="eclair",
                        direction_id=self.direction.id,
                        cycle_date=date.today() + timedelta(days=1),
                        opens_at=now + timedelta(hours=1),
                        closes_at=now + timedelta(hours=2),
                        status="OPEN",
                    ),
                    SupplyRequestCycle(
                        tenant_id="eclair",
                        direction_id=self.direction.id,
                        cycle_date=date.today() - timedelta(days=1),
                        opens_at=now - timedelta(hours=3),
                        closes_at=now - timedelta(hours=2),
                        status="CLOSED",
                    ),
                    SupplyRequestCycle(
                        tenant_id="eclair",
                        direction_id=self.inactive_direction.id,
                        cycle_date=date.today(),
                        opens_at=now - timedelta(hours=1),
                        closes_at=now + timedelta(hours=1),
                        status="OPEN",
                    ),
                ]
            )
            self.kg = SupplyUnit(
                tenant_id="eclair",
                code="KG",
                name_ru="килограмм",
                short_name_ru="кг",
                allows_fraction=True,
            )
            session.add(self.kg)
            session.flush()
            session.add(
                SupplyProduct(
                    tenant_id="eclair",
                    name="Картофель",
                    normalized_name=normalize_product_text("Картофель"),
                    default_unit_id=self.kg.id,
                    request_direction_id=self.direction.id,
                )
            )

        def override_get_db():
            with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app, client=("127.0.0.1", 50000))

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        token_rate_guard.clear()
        settings.default_tenant_id = self.previous_tenant_id
        self.engine.dispose()

    def payload(self, multiline_text: str = "Картофель 10 кг") -> dict:
        return {
            "department_id": str(self.department.id),
            "cycle_id": str(self.open_cycle.id),
            "author_name": " Анна ",
            "author_phone": None,
            "multiline_text": multiline_text,
        }

    def create_request(self, multiline_text: str = "Картофель 10 кг") -> dict:
        response = self.client.post(
            "/public/supply/requests",
            json=self.payload(multiline_text),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_public_references_are_tenant_safe_and_only_current_open(self) -> None:
        departments = self.client.get("/public/supply/departments")
        cycles = self.client.get(
            "/public/supply/request-cycles",
            params={"department_id": str(self.department.id)},
        )
        self.assertEqual(departments.status_code, 200)
        self.assertEqual(
            departments.json(),
            [
                {
                    "id": str(self.department.id),
                    "code": "М15",
                    "name": "Матросова 15",
                    "display_order": 10,
                }
            ],
        )
        self.assertEqual(cycles.status_code, 200)
        self.assertEqual(len(cycles.json()), 1)
        cycle = cycles.json()[0]
        self.assertEqual(cycle["id"], str(self.open_cycle.id))
        self.assertGreater(cycle["seconds_until_close"], 0)
        self.assertNotIn("tenant_id", cycle)
        self.assertEqual(
            self.client.get(
                "/public/supply/request-cycles",
                params={"department_id": str(self.foreign_department.id)},
            ).json(),
            [],
        )

    def test_create_recognizes_and_stores_only_token_hash(self) -> None:
        created = self.create_request("  Картофель 10 кг\n\nНеизвестное 2 кг ")
        self.assertEqual(created["status"], "DRAFT")
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["author_name"], "Анна")
        self.assertEqual(created["lines"][0]["match_status"], "MATCHED")
        self.assertEqual(created["lines"][1]["match_status"], "NEEDS_REVIEW")
        token = created["public_token"]
        self.assertNotIn(token, repr(created["lines"]))
        with self.session_factory() as session:
            stored = session.scalar(select(SupplyRequest))
            self.assertNotEqual(stored.public_token_hash, token)
            self.assertEqual(stored.public_token_hash, hash_public_token(token))
            self.assertEqual(stored.source_type, "PUBLIC_FORM")
            self.assertIsNone(stored.created_by_user_id)
            self.assertIsNotNone(stored.source_ip_hash)
        restored = self.client.get(f"/public/supply/requests/{token}")
        self.assertEqual(restored.status_code, 200, restored.text)
        forbidden = {
            "tenant_id",
            "created_by_user_id",
            "source_ip_hash",
            "public_token_hash",
            "match_method",
            "matched_by_user_id",
            "match_notes",
            "product_id",
        }
        self.assertTrue(forbidden.isdisjoint(restored.text))

    def test_invalid_expired_and_foreign_tokens_are_generic(self) -> None:
        created = self.create_request()
        token = created["public_token"]
        with self.session_factory.begin() as session:
            stored = session.scalar(select(SupplyRequest))
            stored.public_token_expires_at = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        expired = self.client.get(f"/public/supply/requests/{token}")
        invalid = self.client.get("/public/supply/requests/not-a-token")
        self.assertEqual(expired.status_code, 404)
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(expired.json(), invalid.json())

    def test_duplicate_request_does_not_disclose_existing_request(self) -> None:
        self.create_request()
        duplicate = self.client.post(
            "/public/supply/requests",
            json=self.payload(),
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            duplicate.json()["detail"]["code"],
            "SUPPLY_REQUEST_ALREADY_EXISTS",
        )
        self.assertNotIn("request_id", duplicate.text)
        self.assertNotIn("request_number", duplicate.text)

    def test_body_and_line_limits_reject_empty_or_excessive_input(self) -> None:
        empty = self.client.post(
            "/public/supply/requests",
            json=self.payload("\n \n"),
        )
        long_line = self.client.post(
            "/public/supply/requests",
            json=self.payload("x" * 1001),
        )
        oversized = self.client.post(
            "/public/supply/requests",
            content=b"{}",
            headers={
                "content-type": "application/json",
                "content-length": "24001",
            },
        )
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(long_line.status_code, 422)
        self.assertEqual(oversized.status_code, 413)

    def test_update_lines_recognizes_duplicates_and_checks_version(self) -> None:
        created = self.create_request()
        token = created["public_token"]
        updated = self.client.put(
            f"/public/supply/requests/{token}/lines",
            json={
                "expected_version": created["version"],
                "multiline_text": "Картофель 1 кг\nКартофель 2 кг",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["version"], 2)
        self.assertTrue(
            all(
                line["duplicate_status"] == "SUSPECTED"
                for line in updated.json()["lines"]
            )
        )
        stale = self.client.put(
            f"/public/supply/requests/{token}/lines",
            json={
                "expected_version": 1,
                "multiline_text": "Картофель 3 кг",
            },
        )
        self.assertEqual(stale.status_code, 409)
        blocked = self.client.post(
            f"/public/supply/requests/{token}/submit",
            json={"expected_version": 2},
        )
        self.assertEqual(
            blocked.json()["detail"]["code"],
            "SUPPLY_REQUEST_DUPLICATES_PRESENT",
        )

    def test_submit_requires_unrecognized_confirmation_and_is_terminal(self) -> None:
        created = self.create_request("Что-нибудь необычное")
        token = created["public_token"]
        first = self.client.post(
            f"/public/supply/requests/{token}/submit",
            json={"expected_version": created["version"]},
        )
        self.assertEqual(first.status_code, 409)
        self.assertEqual(
            first.json()["detail"]["code"],
            "SUPPLY_UNRECOGNIZED_CONFIRMATION_REQUIRED",
        )
        submitted = self.client.post(
            f"/public/supply/requests/{token}/submit",
            json={
                "expected_version": created["version"],
                "confirm_unrecognized": True,
            },
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["status"], "SUBMITTED")
        self.assertEqual(submitted.json()["version"], 2)
        edit = self.client.put(
            f"/public/supply/requests/{token}/lines",
            json={
                "expected_version": 2,
                "multiline_text": "Картофель 2 кг",
            },
        )
        self.assertEqual(edit.status_code, 409)

    def test_cycle_closing_blocks_recognize_and_submit(self) -> None:
        created = self.create_request()
        token = created["public_token"]
        with self.session_factory.begin() as session:
            cycle = session.get(SupplyRequestCycle, self.open_cycle.id)
            cycle.status = "CLOSED"
        recognize = self.client.post(
            f"/public/supply/requests/{token}/recognize",
            json={"expected_version": created["version"]},
        )
        submit = self.client.post(
            f"/public/supply/requests/{token}/submit",
            json={"expected_version": created["version"]},
        )
        self.assertEqual(recognize.status_code, 409)
        self.assertEqual(submit.status_code, 409)
        self.assertEqual(
            recognize.json()["detail"]["code"],
            "SUPPLY_REQUEST_CYCLE_CLOSED",
        )

    def test_create_rate_limit_is_database_backed(self) -> None:
        now = datetime.now(timezone.utc)
        with self.session_factory.begin() as session:
            for index in range(5):
                department = Department(
                    tenant_id="eclair",
                    code=f"D{index}",
                    name=f"Подразделение {index}",
                )
                cycle = SupplyRequestCycle(
                    tenant_id="eclair",
                    direction_id=self.direction.id,
                    cycle_date=date.today() + timedelta(days=index + 10),
                    opens_at=now - timedelta(hours=1),
                    closes_at=now + timedelta(hours=1),
                    status="OPEN",
                )
                session.add_all([department, cycle])
                session.flush()
                session.add(
                    SupplyRequest(
                        tenant_id="eclair",
                        public_number=f"RATE-{index}",
                        department_id=department.id,
                        direction_id=self.direction.id,
                        cycle_id=cycle.id,
                        status="DRAFT",
                        source_type="PUBLIC_FORM",
                        raw_input="x",
                        public_token_hash=f"{index:064d}",
                        public_created_at=now,
                        source_ip_hash=hash_source_ip("127.0.0.1"),
                    )
                )
        response = self.client.post(
            "/public/supply/requests",
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 429, response.text)


if __name__ == "__main__":
    unittest.main()
