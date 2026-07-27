import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.supply import (
    Department,
    SupplyDepartmentDebt,
    SupplyDepartmentDebtEvent,
    SupplyLineAllocation,
    SupplyProduct,
    SupplyProductAlias,
    SupplyProductCategory,
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
from app.supply.public_service import hash_public_token


class SupplyFulfillmentApiTests(unittest.TestCase):
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
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
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
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory.begin() as session:
            session.add(User(
                id=2,
                username="admin",
                display_name="Администратор",
                hashed_password="unused",
                is_active=True,
                is_admin=True,
            ))
            self.department = Department(
                tenant_id="eclair", code="М15", name="Матросова 15"
            )
            self.direction = SupplyRequestDirection(
                tenant_id="eclair", code="MAIN", name="Основной"
            )
            self.unit = SupplyUnit(
                tenant_id="eclair",
                code="KG",
                name_ru="килограмм",
                short_name_ru="кг",
                allows_fraction=True,
            )
            session.add_all([self.department, self.direction, self.unit])
            session.flush()
            self.product = SupplyProduct(
                tenant_id="eclair",
                name="Сахар",
                normalized_name=normalize_product_text("Сахар"),
                default_unit_id=self.unit.id,
                request_direction_id=self.direction.id,
            )
            session.add(self.product)

        def override_get_db():
            with self.session_factory() as session:
                yield session

        def override_current_user():
            with self.session_factory() as session:
                return session.get(User, 2)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.client = TestClient(app)
        self.counter = 0

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        settings.default_tenant_id = self.previous_tenant_id
        self.engine.dispose()

    def create_planned_request(
        self,
        *,
        requested: str = "10",
        transfer: str = "6",
        purchase: str = "2",
        cancel: str = "0",
        public_token: str | None = None,
    ) -> dict:
        self.counter += 1
        now = datetime.now(timezone.utc)
        with self.session_factory.begin() as session:
            cycle = SupplyRequestCycle(
                tenant_id="eclair",
                direction_id=self.direction.id,
                cycle_date=date.today() + timedelta(days=self.counter),
                opens_at=now - timedelta(hours=1),
                closes_at=now + timedelta(hours=1),
                status="OPEN",
            )
            session.add(cycle)
            session.flush()
            request = SupplyRequest(
                tenant_id="eclair",
                public_number=f"ЗАЯВКА-TEST-{self.counter:03d}",
                department_id=self.department.id,
                direction_id=self.direction.id,
                cycle_id=cycle.id,
                status="PLANNED",
                source_type="INTERNAL",
                raw_input=f"Сахар {requested} кг",
                planned_at=now,
                planned_by_user_id=2,
                public_token_hash=(
                    hash_public_token(public_token) if public_token else None
                ),
                public_token_expires_at=(
                    now + timedelta(days=1) if public_token else None
                ),
                public_author_name="Анна" if public_token else None,
            )
            session.add(request)
            session.flush()
            line = SupplyRequestLine(
                request_id=request.id,
                position=1,
                raw_text=f"Сахар {requested} кг",
                product_id=self.product.id,
                requested_unit_id=self.unit.id,
                quantity=Decimal(requested),
                match_status="MATCHED",
                match_method="MANUAL",
            )
            session.add(line)
            session.flush()
            quantities = {
                "TRANSFER": transfer,
                "PURCHASE": purchase,
                "CANCEL": cancel,
            }
            allocations = []
            for action, quantity in quantities.items():
                if Decimal(quantity) <= 0:
                    continue
                allocation = SupplyLineAllocation(
                    tenant_id="eclair",
                    request_id=request.id,
                    request_line_id=line.id,
                    action=action,
                    planned_quantity=Decimal(quantity),
                    unit_id=self.unit.id,
                    created_by_user_id=2,
                )
                session.add(allocation)
                allocations.append(allocation)
            session.flush()
            return {
                "id": str(request.id),
                "line_id": str(line.id),
                "version": request.version,
                "allocations": {
                    allocation.action: str(allocation.id)
                    for allocation in allocations
                },
            }

    def fulfill(self, request: dict, **quantities: str):
        items = [
            {
                "allocation_id": request["allocations"][action],
                "fulfilled_quantity": quantity,
                "comment": "факт",
            }
            for action, quantity in quantities.items()
        ]
        return self.client.put(
            f"/supply/requests/{request['id']}/lines/{request['line_id']}/fulfillment",
            json={"expected_version": request["version"], "items": items},
        )

    def test_partial_fulfillment_creates_idempotent_debt_and_history(self) -> None:
        request = self.create_planned_request()
        response = self.fulfill(request, TRANSFER="4", PURCHASE="1")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "PARTIALLY_FULFILLED")
        self.assertEqual(body["version"], request["version"] + 1)
        self.assertEqual(Decimal(body["lines"][0]["fulfilled_total"]), Decimal("5"))
        self.assertEqual(Decimal(body["lines"][0]["unresolved_quantity"]), Decimal("5"))
        self.assertEqual(Decimal(body["lines"][0]["active_debt_quantity"]), Decimal("5"))

        no_op = self.client.put(
            f"/supply/requests/{request['id']}/lines/{request['line_id']}/fulfillment",
            json={
                "expected_version": body["version"],
                "items": [
                    {
                        "allocation_id": request["allocations"]["TRANSFER"],
                        "fulfilled_quantity": "4",
                        "comment": "факт",
                    },
                    {
                        "allocation_id": request["allocations"]["PURCHASE"],
                        "fulfilled_quantity": "1",
                        "comment": "факт",
                    },
                ],
            },
        )
        self.assertEqual(no_op.status_code, 200, no_op.text)
        self.assertEqual(no_op.json()["version"], body["version"])
        debts = self.client.get("/supply/debts").json()
        self.assertEqual(debts["total"], 1)
        self.assertEqual(
            Decimal(debts["items"][0]["outstanding_quantity"]), Decimal("5")
        )
        self.assertEqual(
            [event["event_type"] for event in debts["items"][0]["events"]],
            ["CREATED"],
        )
        summary = self.client.get("/supply/summary/dashboard")
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["active_debts"], 1)
        self.assertEqual(summary.json()["requests_in_progress"], 1)

    def test_validation_rollback_and_full_fulfillment(self) -> None:
        request = self.create_planned_request()
        excessive = self.fulfill(request, TRANSFER="7")
        self.assertEqual(excessive.status_code, 422, excessive.text)
        card = self.client.get(f"/supply/requests/{request['id']}").json()
        self.assertEqual(card["version"], request["version"])
        self.assertEqual(Decimal(card["lines"][0]["fulfilled_total"]), Decimal("0"))

        complete = self.client.post(
            f"/supply/requests/{request['id']}/fulfill-as-planned",
            json={"expected_version": request["version"]},
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        self.assertEqual(complete.json()["status"], "PARTIALLY_FULFILLED")
        self.assertEqual(
            Decimal(complete.json()["lines"][0]["unresolved_quantity"]),
            Decimal("2"),
        )
        self.assertEqual(self.client.get("/supply/debts").json()["total"], 1)

        fully_planned = self.create_planned_request(transfer="8", purchase="2")
        fulfilled = self.client.post(
            f"/supply/requests/{fully_planned['id']}/fulfill-as-planned",
            json={"expected_version": fully_planned["version"]},
        )
        self.assertEqual(fulfilled.status_code, 200, fulfilled.text)
        self.assertEqual(fulfilled.json()["status"], "FULFILLED")
        immutable = self.fulfill(fully_planned, TRANSFER="5")
        self.assertEqual(immutable.status_code, 409)

    def test_debt_inclusion_closes_old_debt_first(self) -> None:
        first = self.create_planned_request()
        first_result = self.fulfill(first, TRANSFER="4", PURCHASE="1").json()
        debt = self.client.get("/supply/debts").json()["items"][0]

        second = self.create_planned_request(requested="7", transfer="7")
        second_card = self.client.get(f"/supply/requests/{second['id']}").json()
        self.assertEqual(
            second_card["lines"][0]["debt_inclusion_status"],
            "COVERED_BY_REQUEST",
        )
        second_result = self.client.post(
            f"/supply/requests/{second['id']}/fulfill-as-planned",
            json={"expected_version": second["version"]},
        )
        self.assertEqual(second_result.status_code, 200, second_result.text)
        self.assertEqual(second_result.json()["status"], "FULFILLED")
        closed = self.client.get(f"/supply/debts/{debt['id']}").json()
        self.assertEqual(closed["status"], "CLOSED")
        self.assertEqual(Decimal(closed["outstanding_quantity"]), Decimal("0"))
        self.assertIn(
            "INCLUDED_IN_REQUEST",
            [event["event_type"] for event in closed["events"]],
        )
        self.assertEqual(first_result["version"], first["version"] + 1)

    def test_smaller_request_requires_and_persists_partial_inclusion(self) -> None:
        first = self.create_planned_request()
        self.fulfill(first, TRANSFER="4", PURCHASE="1")
        debt_before = self.client.get("/supply/debts").json()["items"][0]
        second = self.create_planned_request(requested="3", transfer="3")
        blocked = self.client.post(
            f"/supply/requests/{second['id']}/fulfill-as-planned",
            json={"expected_version": second["version"]},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(
            blocked.json()["detail"]["code"],
            "SUPPLY_DEBT_INCLUSION_CONFIRMATION_REQUIRED",
        )
        unchanged = self.client.get(f"/supply/requests/{second['id']}").json()
        self.assertEqual(unchanged["version"], second["version"])
        confirmed = self.client.post(
            f"/supply/requests/{second['id']}/lines/{second['line_id']}/confirm-debt-inclusion",
            json={
                "expected_version": second["version"],
                "included_quantity": "2",
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(
            confirmed.json()["lines"][0]["debt_inclusion_status"],
            "CONFIRMED_PARTIAL",
        )
        fulfilled = self.client.post(
            f"/supply/requests/{second['id']}/fulfill-as-planned",
            json={"expected_version": confirmed.json()["version"]},
        )
        self.assertEqual(fulfilled.status_code, 200, fulfilled.text)
        debt_after = self.client.get(
            f"/supply/debts/{debt_before['id']}"
        ).json()
        self.assertEqual(
            Decimal(debt_after["outstanding_quantity"]), Decimal("3")
        )
        self.assertEqual(debt_after["cycle_count"], 1)
        self.assertEqual(debt_after["severity"], "PURPLE")

    def test_decreasing_fact_requires_comment_and_recalculates_contribution(self) -> None:
        request = self.create_planned_request()
        first = self.fulfill(request, TRANSFER="4", PURCHASE="1").json()
        without_comment = self.client.put(
            f"/supply/requests/{request['id']}/lines/{request['line_id']}/fulfillment",
            json={
                "expected_version": first["version"],
                "items": [{
                    "allocation_id": request["allocations"]["TRANSFER"],
                    "fulfilled_quantity": "3",
                    "comment": None,
                }],
            },
        )
        self.assertEqual(without_comment.status_code, 422)
        decreased = self.client.put(
            f"/supply/requests/{request['id']}/lines/{request['line_id']}/fulfillment",
            json={
                "expected_version": first["version"],
                "items": [{
                    "allocation_id": request["allocations"]["TRANSFER"],
                    "fulfilled_quantity": "3",
                    "comment": "исправление факта",
                }],
            },
        )
        self.assertEqual(decreased.status_code, 200, decreased.text)
        self.assertEqual(
            Decimal(decreased.json()["lines"][0]["unresolved_quantity"]),
            Decimal("6"),
        )
        debt = self.client.get("/supply/debts").json()["items"][0]
        self.assertEqual(Decimal(debt["outstanding_quantity"]), Decimal("6"))

    def test_manual_partial_close_cancel_version_and_tenant_isolation(self) -> None:
        request = self.create_planned_request()
        self.fulfill(request, TRANSFER="4", PURCHASE="1")
        debt = self.client.get("/supply/debts").json()["items"][0]
        stale = self.client.post(
            f"/supply/debts/{debt['id']}/close",
            json={
                "expected_version": debt["version"] + 1,
                "quantity": "1",
                "comment": "вне заявки",
            },
        )
        self.assertEqual(stale.status_code, 409)
        partial = self.client.post(
            f"/supply/debts/{debt['id']}/close",
            json={
                "expected_version": debt["version"],
                "quantity": "2",
                "comment": "доставлено отдельно",
            },
        )
        self.assertEqual(partial.status_code, 200, partial.text)
        self.assertEqual(
            Decimal(partial.json()["outstanding_quantity"]), Decimal("3")
        )
        cancelled = self.client.post(
            f"/supply/debts/{debt['id']}/cancel",
            json={
                "expected_version": partial.json()["version"],
                "comment": "потребность отменена",
            },
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        self.assertEqual(
            Decimal(cancelled.json()["outstanding_quantity"]), Decimal("0")
        )
        self.assertEqual(
            self.client.get("/supply/debts", params={"status": "ACTIVE"}).json()["total"],
            0,
        )

    def test_public_status_exposes_only_safe_plan_fact_and_debt_totals(self) -> None:
        request = self.create_planned_request(public_token="public-safe-token")
        self.fulfill(request, TRANSFER="4", PURCHASE="1")
        response = self.client.get(
            "/public/supply/requests/public-safe-token"
        )
        self.assertEqual(response.status_code, 200, response.text)
        line = response.json()["lines"][0]
        self.assertEqual(Decimal(line["confirmed_quantity"]), Decimal("8"))
        self.assertEqual(Decimal(line["fulfilled_quantity"]), Decimal("5"))
        self.assertEqual(Decimal(line["unresolved_quantity"]), Decimal("5"))
        self.assertEqual(Decimal(line["debt_quantity"]), Decimal("5"))
        serialized = response.text
        self.assertNotIn("fulfillment_comment", serialized)
        self.assertNotIn("allocation_id", serialized)
        self.assertNotIn("fulfilled_by_user_id", serialized)

    def test_debt_severity_filters_and_critical_summary(self) -> None:
        request = self.create_planned_request()
        self.fulfill(request, TRANSFER="4", PURCHASE="1")
        debt = self.client.get("/supply/debts").json()["items"][0]
        expected = {
            0: "YELLOW",
            1: "PURPLE",
            2: "RED",
            3: "CRITICAL",
        }
        for cycle_count, severity in expected.items():
            with self.session_factory.begin() as session:
                stored = session.get(SupplyDepartmentDebt, UUID(debt["id"]))
                stored.cycle_count = cycle_count
            response = self.client.get(
                "/supply/debts",
                params={"severity": severity},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["total"], 1)
            self.assertEqual(response.json()["items"][0]["severity"], severity)

        summary = self.client.get("/supply/summary/dashboard")
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["critical_debts"], 1)

    def test_fulfillment_and_debt_endpoints_require_admin(self) -> None:
        request = self.create_planned_request()

        def override_non_admin():
            with self.session_factory() as session:
                user = session.get(User, 2)
                user.is_admin = False
                return user

        app.dependency_overrides[get_current_user] = override_non_admin
        self.assertEqual(self.client.get("/supply/debts").status_code, 403)
        denied = self.client.put(
            f"/supply/requests/{request['id']}/lines/{request['line_id']}/fulfillment",
            json={"expected_version": request["version"], "items": []},
        )
        self.assertEqual(denied.status_code, 403)

        app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.get("/supply/debts").status_code, 401)


if __name__ == "__main__":
    unittest.main()
