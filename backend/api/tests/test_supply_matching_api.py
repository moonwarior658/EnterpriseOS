import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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
from app.supply.normalization import normalize_product_text


UNIT_DATA = (
    ("KG", "килограмм", "кг", True),
    ("L", "литр", "л", True),
    ("PCS", "штука", "шт", False),
    ("PACK", "упаковка", "уп", False),
    ("BOX", "коробка", "кор", False),
    ("ROLL", "рулон", "рул", False),
)


class SupplyMatchingApiTests(unittest.TestCase):
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
            self.department = Department(
                tenant_id="eclair",
                code="М15",
                name="Матросова 15",
                display_order=10,
            )
            self.direction = SupplyRequestDirection(
                tenant_id="eclair",
                code="MAIN",
                name="Основной",
                display_order=10,
            )
            session.add_all([self.department, self.direction])
            self.units = {
                code: SupplyUnit(
                    tenant_id="eclair",
                    code=code,
                    name_ru=name,
                    short_name_ru=short_name,
                    allows_fraction=allows_fraction,
                )
                for code, name, short_name, allows_fraction in UNIT_DATA
            }
            session.add_all(self.units.values())
            session.flush()
            self.milk = self._add_product(session, "Молоко", "L")
            self.cream = self._add_product(session, "Сливки", "L")
            session.add(
                SupplyProductAlias(
                    tenant_id="eclair",
                    product=self.cream,
                    alias="Сливочки",
                    normalized_alias="сливочки",
                )
            )
            self.inactive_product = self._add_product(
                session,
                "Неактивный товар",
                "KG",
                is_active=False,
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

    def _add_product(
        self,
        session,
        name: str,
        unit_code: str,
        *,
        tenant_id: str = "eclair",
        is_active: bool = True,
    ) -> SupplyProduct:
        product = SupplyProduct(
            tenant_id=tenant_id,
            name=name,
            normalized_name=normalize_product_text(name),
            default_unit=self.units[unit_code],
            request_direction=self.direction,
            is_active=is_active,
            archived_at=None if is_active else datetime.now(timezone.utc),
            archived_by_user_id=None if is_active else 2,
        )
        session.add(product)
        session.flush()
        return product

    def create_request(self, *raw_lines: str) -> dict:
        self.cycle_counter += 1
        with self.session_factory.begin() as session:
            cycle = SupplyRequestCycle(
                tenant_id="eclair",
                direction_id=self.direction.id,
                cycle_date=date(2026, 1, 1)
                + timedelta(days=self.cycle_counter),
                opens_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                closes_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
                status="OPEN",
            )
            session.add(cycle)
            session.flush()
            cycle_id = cycle.id
        response = self.client.post(
            "/supply/requests",
            json={
                "department_id": str(self.department.id),
                "direction_id": str(self.direction.id),
                "cycle_id": str(cycle_id),
                "raw_input": "\n".join(raw_lines),
                "lines": [{"raw_text": line} for line in raw_lines],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def recognize(self, request_id: str, *, force: bool = False):
        detail = self.client.get(f"/supply/requests/{request_id}")
        expected_version = (
            detail.json()["version"] if detail.status_code == 200 else 1
        )
        return self.client.post(
            f"/supply/requests/{request_id}/recognize",
            json={
                "expected_version": expected_version,
                "force": force,
            },
        )

    def match(self, request_id: str, line_id: str, payload: dict):
        detail = self.client.get(f"/supply/requests/{request_id}")
        expected_version = (
            detail.json()["version"] if detail.status_code == 200 else 1
        )
        return self.client.post(
            f"/supply/requests/{request_id}/lines/{line_id}/match",
            json={"expected_version": expected_version, **payload},
        )

    def test_recognition_matches_product_alias_and_keeps_unknown_for_review(
        self,
    ) -> None:
        created = self.create_request(
            "  Молоко   5 л  ",
            "Сливочки 2,5 литра",
            "Неизвестно 3 уп",
            "Молоко пять л",
            "Неактивный товар 1 кг",
        )
        response = self.recognize(created["id"])
        self.assertEqual(response.status_code, 200, response.text)
        summary = response.json()
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["matched"], 2)
        self.assertEqual(summary["needs_review"], 3)
        self.assertEqual(summary["rejected"], 0)
        self.assertEqual(summary["skipped"], 0)

        detail = self.client.get(
            f"/supply/requests/{created['id']}"
        ).json()
        exact, alias, unknown, invalid, inactive = detail["lines"]
        self.assertEqual(exact["raw_text"], "  Молоко   5 л  ")
        self.assertEqual(exact["parsed_name"], "Молоко")
        self.assertEqual(Decimal(exact["parsed_quantity"]), Decimal("5"))
        self.assertEqual(exact["parsed_unit"]["code"], "L")
        self.assertEqual(exact["product"]["id"], str(self.milk.id))
        self.assertEqual(exact["requested_unit"]["code"], "L")
        self.assertEqual(exact["match_method"], "EXACT_PRODUCT")
        self.assertEqual(Decimal(exact["match_confidence"]), Decimal("1"))
        self.assertIsNone(exact["matched_by_user_id"])
        self.assertEqual(alias["product"]["id"], str(self.cream.id))
        self.assertEqual(alias["match_method"], "EXACT_ALIAS")
        self.assertEqual(
            Decimal(alias["parsed_quantity"]),
            Decimal("2.5"),
        )
        self.assertEqual(unknown["parsed_name"], "Неизвестно")
        self.assertEqual(unknown["parsed_unit"]["code"], "PACK")
        self.assertIsNone(unknown["product"])
        self.assertEqual(unknown["match_status"], "NEEDS_REVIEW")
        self.assertEqual(Decimal(unknown["quantity"]), Decimal("3"))
        self.assertEqual(unknown["requested_unit"]["code"], "PACK")
        self.assertEqual(unknown["working_name"], "Неизвестно")
        self.assertIsNone(invalid["parsed_name"])
        self.assertIsNone(invalid["parsed_quantity"])
        self.assertIsNone(invalid["parsed_unit"])
        self.assertEqual(inactive["parsed_name"], "Неактивный товар")
        self.assertIsNone(inactive["product"])
        self.assertEqual(detail["version"], 2)

    def test_archive_preserves_old_match_and_restore_enables_new_matches(
        self,
    ) -> None:
        existing = self.create_request("Молоко 1 л")
        recognized = self.recognize(existing["id"])
        self.assertEqual(recognized.status_code, 200, recognized.text)

        archived = self.client.post(
            f"/supply/products/{self.milk.id}/archive"
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        preserved = self.client.get(
            f"/supply/requests/{existing['id']}"
        ).json()["lines"][0]
        self.assertEqual(preserved["match_status"], "MATCHED")
        self.assertEqual(preserved["product_id"], str(self.milk.id))

        fresh = self.create_request("Молоко 2 л")
        fresh_recognition = self.recognize(fresh["id"])
        self.assertEqual(fresh_recognition.status_code, 200)
        self.assertEqual(fresh_recognition.json()["matched"], 0)
        manual = self.match(
            fresh["id"],
            fresh["lines"][0]["id"],
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["L"].id),
                "quantity": "2",
            },
        )
        self.assertEqual(manual.status_code, 422)

        restored = self.client.post(
            f"/supply/products/{self.milk.id}/restore"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        available_again = self.create_request("Молоко 3 л")
        recognition = self.recognize(available_again["id"])
        self.assertEqual(recognition.status_code, 200)
        self.assertEqual(recognition.json()["matched"], 1)

    def test_fraction_policy_applies_to_recognition_and_manual_match(
        self,
    ) -> None:
        created = self.create_request(
            "Молоко 2.5 л",
            "Неизвестно 1,5 шт",
        )
        response = self.recognize(created["id"])
        self.assertEqual(response.status_code, 200, response.text)
        detail = self.client.get(
            f"/supply/requests/{created['id']}"
        ).json()
        self.assertEqual(detail["lines"][0]["match_status"], "MATCHED")
        self.assertEqual(
            detail["lines"][1]["match_status"],
            "NEEDS_REVIEW",
        )
        self.assertIsNone(detail["lines"][1]["parsed_quantity"])

        line_id = detail["lines"][1]["id"]
        invalid = self.match(
            created["id"],
            line_id,
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["PCS"].id),
                "quantity": "1.5",
            },
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)
        valid = self.match(
            created["id"],
            line_id,
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["KG"].id),
                "quantity": "1.5",
            },
        )
        self.assertEqual(valid.status_code, 200, valid.text)

    def test_manual_match_reject_reset_and_force_are_transactional(self) -> None:
        created = self.create_request("Молочко тестовое 2 л")
        recognized = self.recognize(created["id"]).json()
        line_id = recognized["results"][0]["line_id"]

        manual = self.match(
            created["id"],
            line_id,
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["L"].id),
                "quantity": "4",
                "notes": "Подтверждено вручную",
            },
        )
        self.assertEqual(manual.status_code, 200, manual.text)
        body = manual.json()
        self.assertEqual(body["match_method"], "MANUAL")
        self.assertEqual(body["matched_by_user_id"], 2)
        self.assertEqual(body["match_notes"], "Подтверждено вручную")
        self.assertEqual(body["product"]["id"], str(self.milk.id))

        skipped = self.recognize(created["id"]).json()
        self.assertEqual(skipped["skipped"], 1)
        self.assertEqual(skipped["matched"], 0)
        self.assertEqual(
            skipped["total"],
            skipped["matched"]
            + skipped["needs_review"]
            + skipped["rejected"]
            + skipped["skipped"],
        )
        self.assertEqual(skipped["results"][0]["match_method"], "MANUAL")
        self.assertEqual(
            self.client.get(f"/supply/requests/{created['id']}").json()[
                "version"
            ],
            3,
        )

        forced = self.recognize(created["id"], force=True).json()
        self.assertEqual(forced["skipped"], 0)
        self.assertEqual(
            forced["results"][0]["match_method"],
            "EXACT_ALIAS",
        )
        detail = self.client.get(
            f"/supply/requests/{created['id']}"
        ).json()
        self.assertEqual(detail["version"], 4)
        self.assertIsNone(detail["lines"][0]["matched_by_user_id"])
        self.assertIsNone(detail["lines"][0]["match_notes"])

        rejected = self.match(
            created["id"],
            line_id,
            {"action": "REJECT", "notes": "Не заказывать"},
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        body = rejected.json()
        self.assertEqual(body["match_status"], "REJECTED")
        self.assertEqual(body["match_method"], "MANUAL")
        self.assertIsNone(body["product_id"])
        self.assertIsNone(body["requested_unit_id"])
        self.assertIsNone(body["quantity"])
        self.assertEqual(body["parsed_name"], "Молочко тестовое")

        reset = self.match(
            created["id"],
            line_id,
            {"action": "RESET"},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        body = reset.json()
        self.assertEqual(body["match_status"], "UNPROCESSED")
        self.assertIsNone(body["match_method"])
        self.assertIsNone(body["matched_at"])
        self.assertIsNone(body["matched_by_user_id"])
        self.assertIsNone(body["match_notes"])
        self.assertEqual(body["parsed_name"], "Молочко тестовое")
        self.assertEqual(body["raw_text"], "Молочко тестовое 2 л")

    def test_tenant_scope_cancelled_state_and_admin_access(self) -> None:
        created = self.create_request("Молоко 1 л")
        line_id = created["lines"][0]["id"]
        with self.session_factory.begin() as session:
            foreign_unit = SupplyUnit(
                tenant_id="other",
                code="L",
                name_ru="литр",
                short_name_ru="л",
                allows_fraction=True,
            )
            foreign_product = SupplyProduct(
                tenant_id="other",
                name="Чужой товар",
                normalized_name="чужой товар",
                default_unit=foreign_unit,
            )
            session.add_all([foreign_unit, foreign_product])
            session.flush()
            foreign_unit_id = foreign_unit.id
            foreign_product_id = foreign_product.id

        for product_id, unit_id in (
            (foreign_product_id, self.units["L"].id),
            (self.milk.id, foreign_unit_id),
        ):
            response = self.match(
                created["id"],
                line_id,
                {
                    "action": "MATCH",
                    "product_id": str(product_id),
                    "unit_id": str(unit_id),
                    "quantity": "1",
                },
            )
            self.assertEqual(response.status_code, 404, response.text)

        self.current_user_id = 1
        self.assertEqual(self.recognize(created["id"]).status_code, 403)
        self.assertEqual(
            self.match(
                created["id"],
                line_id,
                {"action": "RESET"},
            ).status_code,
            403,
        )
        app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.recognize(created["id"]).status_code, 401)
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.current_user_id = 2

        with self.session_factory.begin() as session:
            request = session.get(SupplyRequest, UUID(created["id"]))
            request.status = "SUBMITTED"
        submitted = self.recognize(created["id"])
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(
            self.client.get(f"/supply/requests/{created['id']}").json()[
                "status"
            ],
            "SUBMITTED",
        )

        with self.session_factory.begin() as session:
            request = session.get(SupplyRequest, UUID(created["id"]))
            request.status = "CANCELLED"
        self.assertEqual(self.recognize(created["id"]).status_code, 409)
        self.assertEqual(
            self.match(
                created["id"],
                line_id,
                {"action": "RESET"},
            ).status_code,
            409,
        )

    def test_invalid_body_missing_or_cross_request_line_is_rejected(self) -> None:
        first = self.create_request("Молоко 1 л")
        second = self.create_request("Сливки 1 л")
        line_id = first["lines"][0]["id"]
        self.assertEqual(
            self.match(
                first["id"],
                line_id,
                {"action": "MATCH", "quantity": "1"},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.match(
                first["id"],
                line_id,
                {
                    "action": "RESET",
                    "product_id": str(self.milk.id),
                },
            ).status_code,
            422,
        )
        self.assertEqual(
            self.match(
                second["id"],
                line_id,
                {"action": "RESET"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.match(
                first["id"],
                str(uuid4()),
                {"action": "RESET"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.recognize(str(uuid4())).status_code,
            404,
        )

    def test_manual_alias_is_approved_and_applied_with_usage_counter(self) -> None:
        first = self.create_request("молочко 2 л")
        recognized = self.recognize(first["id"])
        self.assertEqual(recognized.status_code, 200, recognized.text)
        detail = self.client.get(f"/supply/requests/{first['id']}").json()
        line = detail["lines"][0]
        matched = self.match(
            first["id"],
            line["id"],
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["L"].id),
                "quantity": "2",
            },
        )
        self.assertEqual(matched.status_code, 200, matched.text)
        with self.session_factory() as session:
            alias = session.query(SupplyProductAlias).filter_by(
                normalized_alias="молочко"
            ).one()
            self.assertEqual(alias.status, "APPROVED")
            self.assertEqual(alias.created_by_user_id, 2)
            self.assertEqual(alias.successful_application_count, 1)
            self.assertIsNotNone(alias.last_applied_at)

        second = self.create_request("молочко 3 л")
        second_line = second["lines"][0]
        second_match = self.match(
            second["id"],
            second_line["id"],
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["L"].id),
                "quantity": "3",
            },
        )
        self.assertEqual(second_match.status_code, 200, second_match.text)
        with self.session_factory() as session:
            alias = session.query(SupplyProductAlias).filter_by(
                normalized_alias="молочко"
            ).one()
            self.assertEqual(alias.successful_application_count, 2)
            self.assertIsNotNone(alias.last_applied_at)

        third = self.create_request("молочко 4 л")
        self.assertEqual(self.recognize(third["id"]).status_code, 200)
        third_detail = self.client.get(
            f"/supply/requests/{third['id']}"
        ).json()
        self.assertEqual(third_detail["lines"][0]["match_method"], "EXACT_ALIAS")

    def test_manual_alias_conflict_does_not_change_existing_alias(self) -> None:
        with self.session_factory.begin() as session:
            conflict = SupplyProductAlias(
                tenant_id="eclair",
                product_id=self.cream.id,
                alias="Спорное молоко",
                normalized_alias="спорное молоко",
                status="APPROVED",
                successful_application_count=7,
            )
            session.add(conflict)
            session.flush()
            conflict_id = conflict.id

        created = self.create_request("Спорное молоко 2 л")
        line = created["lines"][0]
        response = self.match(
            created["id"],
            line["id"],
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["L"].id),
                "quantity": "2",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "SUPPLY_ALIAS_CONFLICT")
        unchanged_line = self.client.get(
            f"/supply/requests/{created['id']}"
        ).json()["lines"][0]
        self.assertEqual(unchanged_line["match_status"], "UNPROCESSED")
        self.assertIsNone(unchanged_line["product_id"])
        with self.session_factory() as session:
            alias = session.get(SupplyProductAlias, conflict_id)
            self.assertEqual(alias.product_id, self.cream.id)
            self.assertEqual(alias.status, "APPROVED")
            self.assertEqual(alias.successful_application_count, 7)
            self.assertIsNone(alias.last_applied_at)

        with self.session_factory.begin() as session:
            disabled = SupplyProductAlias(
                tenant_id="eclair",
                product_id=self.milk.id,
                alias="Отключённое название",
                normalized_alias="отключенное название",
                status="DISABLED",
                successful_application_count=3,
            )
            session.add(disabled)
            session.flush()
            disabled_id = disabled.id
        disabled_request = self.create_request("Отключённое название 1 л")
        disabled_response = self.match(
            disabled_request["id"],
            disabled_request["lines"][0]["id"],
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["L"].id),
                "quantity": "1",
            },
        )
        self.assertEqual(disabled_response.status_code, 409)
        with self.session_factory() as session:
            alias = session.get(SupplyProductAlias, disabled_id)
            self.assertEqual(alias.status, "DISABLED")
            self.assertEqual(alias.successful_application_count, 3)

    def test_allocations_start_review_and_complete_request_plan(self) -> None:
        created = self.create_request("Молоко 10 л")
        recognized = self.recognize(created["id"])
        self.assertEqual(recognized.status_code, 200, recognized.text)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        line = submitted.json()["lines"][0]
        split = self.client.put(
            f"/supply/requests/{created['id']}/lines/{line['id']}/allocations",
            json={
                "expected_version": submitted.json()["version"],
                "allocations": [
                    {"action": "TRANSFER", "planned_quantity": "4", "unit_id": str(self.units["L"].id)},
                    {"action": "PURCHASE", "planned_quantity": "5", "unit_id": str(self.units["L"].id)},
                    {"action": "CANCEL", "planned_quantity": "1", "unit_id": str(self.units["L"].id)},
                ],
            },
        )
        self.assertEqual(split.status_code, 200, split.text)
        body = split.json()
        self.assertEqual(body["status"], "IN_REVIEW")
        self.assertEqual(body["version"], submitted.json()["version"] + 1)
        self.assertEqual(body["lines"][0]["planning_status"], "COMPLETE")
        self.assertEqual(body["lines"][0]["unallocated_quantity"], "0.000")
        planned = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={"expected_version": body["version"]},
        )
        self.assertEqual(planned.status_code, 200, planned.text)
        self.assertEqual(planned.json()["status"], "PLANNED")
        immutable = self.client.put(
            f"/supply/requests/{created['id']}/lines/{line['id']}/allocations",
            json={"expected_version": planned.json()["version"], "allocations": []},
        )
        self.assertEqual(immutable.status_code, 409)

    def test_allocation_validation_partial_plan_and_version_conflict(self) -> None:
        created = self.create_request("Молоко 10 л", "неизвестно 2 кг")
        self.assertEqual(self.recognize(created["id"]).status_code, 200)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()
        matched_line, unknown_line = submitted["lines"]
        base = f"/supply/requests/{created['id']}/lines/{matched_line['id']}/allocations"

        exceeds = self.client.put(base, json={
            "expected_version": submitted["version"],
            "allocations": [{
                "action": "TRANSFER", "planned_quantity": "11",
                "unit_id": str(self.units["L"].id),
            }],
        })
        self.assertEqual(exceeds.status_code, 422)
        self.assertEqual(
            exceeds.json()["detail"]["code"],
            "SUPPLY_ALLOCATION_EXCEEDS_REQUESTED",
        )
        mismatch = self.client.put(base, json={
            "expected_version": submitted["version"],
            "allocations": [{
                "action": "TRANSFER", "planned_quantity": "5",
                "unit_id": str(self.units["KG"].id),
            }],
        })
        self.assertEqual(mismatch.status_code, 422)
        duplicate = self.client.put(base, json={
            "expected_version": submitted["version"],
            "allocations": [
                {"action": "TRANSFER", "planned_quantity": "2", "unit_id": str(self.units["L"].id)},
                {"action": "TRANSFER", "planned_quantity": "2", "unit_id": str(self.units["L"].id)},
            ],
        })
        self.assertEqual(duplicate.status_code, 422)
        unmatched = self.client.put(
            f"/supply/requests/{created['id']}/lines/{unknown_line['id']}/allocations",
            json={"expected_version": submitted["version"], "allocations": []},
        )
        self.assertEqual(unmatched.status_code, 200, unmatched.text)

        partial = self.client.put(base, json={
            "expected_version": unmatched.json()["version"],
            "allocations": [{
                "action": "PURCHASE", "planned_quantity": "6",
                "unit_id": str(self.units["L"].id),
            }],
        })
        self.assertEqual(partial.status_code, 200, partial.text)
        body = partial.json()
        self.assertEqual(body["lines"][0]["planning_status"], "INCOMPLETE")
        self.assertEqual(body["lines"][0]["unallocated_quantity"], "4.000")
        stale = self.client.put(base, json={
            "expected_version": submitted["version"],
            "allocations": [],
        })
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            stale.json()["detail"]["code"],
            "SUPPLY_REQUEST_VERSION_CONFLICT",
        )
        blocked_plan = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={"expected_version": body["version"]},
        )
        self.assertEqual(blocked_plan.status_code, 409)
        self.assertEqual(
            blocked_plan.json()["detail"]["code"],
            "SUPPLY_REQUEST_PLANNING_INCOMPLETE",
        )

    def test_unmatched_line_can_be_planned_fulfilled_indebted_and_late_matched(
        self,
    ) -> None:
        created = self.create_request("Редкий ингредиент 10 кг")
        recognized = self.recognize(created["id"])
        self.assertEqual(recognized.status_code, 200, recognized.text)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        line = detail["lines"][0]
        self.assertEqual(line["match_status"], "NEEDS_REVIEW")
        self.assertIsNone(line["product_id"])
        self.assertEqual(line["working_name"], "Редкий ингредиент")
        self.assertEqual(Decimal(line["quantity"]), Decimal("10"))
        self.assertEqual(line["requested_unit"]["code"], "KG")
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()

        allocated = self.client.put(
            f"/supply/requests/{created['id']}/lines/{line['id']}/allocations",
            json={
                "expected_version": submitted["version"],
                "allocations": [
                    {
                        "action": "TRANSFER",
                        "planned_quantity": "6",
                        "unit_id": str(self.units["KG"].id),
                    },
                    {
                        "action": "PURCHASE",
                        "planned_quantity": "3",
                        "unit_id": str(self.units["KG"].id),
                    },
                    {
                        "action": "CANCEL",
                        "planned_quantity": "1",
                        "unit_id": str(self.units["KG"].id),
                    },
                ],
            },
        )
        self.assertEqual(allocated.status_code, 200, allocated.text)
        self.assertTrue(allocated.json()["can_plan"])
        planned = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={"expected_version": allocated.json()["version"]},
        )
        self.assertEqual(planned.status_code, 200, planned.text)
        planned_line = planned.json()["lines"][0]
        physical = {
            item["action"]: item["id"]
            for item in planned_line["allocations"]
            if item["action"] != "CANCEL"
        }

        fulfilled = self.client.put(
            f"/supply/requests/{created['id']}/lines/{line['id']}/fulfillment",
            json={
                "expected_version": planned.json()["version"],
                "items": [
                    {
                        "allocation_id": physical["TRANSFER"],
                        "fulfilled_quantity": "4",
                        "comment": "частичная отправка",
                    },
                    {
                        "allocation_id": physical["PURCHASE"],
                        "fulfilled_quantity": "1",
                        "comment": "частичная закупка",
                    },
                ],
            },
        )
        self.assertEqual(fulfilled.status_code, 200, fulfilled.text)
        fulfilled_body = fulfilled.json()
        fulfilled_line = fulfilled_body["lines"][0]
        self.assertEqual(fulfilled_body["status"], "PARTIALLY_FULFILLED")
        self.assertEqual(Decimal(fulfilled_line["fulfilled_total"]), Decimal("5"))
        self.assertEqual(Decimal(fulfilled_line["unresolved_quantity"]), Decimal("4"))
        debt_id = fulfilled_line["active_debt_id"]
        self.assertIsNotNone(debt_id)
        debt = self.client.get(f"/supply/debts/{debt_id}").json()
        self.assertIsNone(debt["product"])
        self.assertEqual(debt["working_name"], "Редкий ингредиент")
        self.assertEqual(Decimal(debt["outstanding_quantity"]), Decimal("4"))
        self.assertEqual([event["event_type"] for event in debt["events"]], ["CREATED"])
        debt_page = self.client.get(
            "/supply/debts",
            params={"status": "ACTIVE", "search": "Редкий ингредиент"},
        )
        self.assertEqual(debt_page.status_code, 200, debt_page.text)
        self.assertEqual(debt_page.json()["total"], 1)
        self.assertEqual(debt_page.json()["items"][0]["id"], debt_id)
        self.assertEqual(
            debt_page.headers["cache-control"],
            "no-store, no-cache, must-revalidate, max-age=0",
        )

        late_match = self.match(
            created["id"],
            line["id"],
            {
                "action": "MATCH",
                "product_id": str(self.milk.id),
                "unit_id": str(self.units["KG"].id),
                "quantity": "10",
            },
        )
        self.assertEqual(late_match.status_code, 200, late_match.text)
        final = self.client.get(f"/supply/requests/{created['id']}").json()
        final_line = final["lines"][0]
        self.assertEqual(final_line["product_id"], str(self.milk.id))
        self.assertEqual(final_line["planned_total"], "10.000")
        self.assertEqual(final_line["fulfilled_total"], "5.000")
        self.assertEqual(final_line["active_debt_id"], debt_id)
        preserved_debt = self.client.get(f"/supply/debts/{debt_id}").json()
        self.assertEqual(preserved_debt["working_name"], "Редкий ингредиент")
        self.assertEqual(len(preserved_debt["events"]), 1)

    def test_admin_corrects_unparsed_line_for_unmatched_planning(self) -> None:
        raw_text = "мусорные пакеты 30л 3 рулона"
        created = self.create_request(raw_text)
        self.assertEqual(self.recognize(created["id"]).status_code, 200)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        line = detail["lines"][0]
        self.assertIsNone(line["quantity"])
        self.assertIsNone(line["requested_unit"])
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()
        endpoint = (
            f"/supply/requests/{created['id']}/lines/{line['id']}"
            "/working-values"
        )
        payload = {
            "request_version": submitted["version"],
            "working_name": "  Мусорные пакеты 30 л  ",
            "requested_quantity": "3",
            "send_quantity": "3",
            "requested_unit_id": str(self.units["ROLL"].id),
        }

        self.current_user_id = 1
        self.assertEqual(
            self.client.patch(endpoint, json=payload).status_code,
            403,
        )
        self.current_user_id = 2

        missing_unit = self.client.patch(
            endpoint,
            json={**payload, "requested_unit_id": str(uuid4())},
        )
        self.assertEqual(missing_unit.status_code, 404)
        with self.session_factory.begin() as session:
            inactive_unit = SupplyUnit(
                tenant_id="eclair",
                code="INACTIVE_ROLL",
                name_ru="неактивный рулон",
                short_name_ru="нерул",
                allows_fraction=False,
                is_active=False,
            )
            session.add(inactive_unit)
            session.flush()
            inactive_unit_id = inactive_unit.id
        inactive = self.client.patch(
            endpoint,
            json={**payload, "requested_unit_id": str(inactive_unit_id)},
        )
        self.assertEqual(inactive.status_code, 422)
        self.assertEqual(
            inactive.json()["detail"]["code"],
            "SUPPLY_UNIT_INACTIVE",
        )

        with self.assertLogs("app.supply.service", level="INFO") as audit:
            corrected = self.client.patch(endpoint, json=payload)
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertIn("actor_user_id=2", audit.output[0])
        self.assertIn("changed_at=", audit.output[0])
        self.assertIn(
            "'working_name': 'мусорные пакеты 30л 3 рулона'",
            audit.output[0],
        )
        self.assertIn(
            "'working_name': 'Мусорные пакеты 30 л'",
            audit.output[0],
        )
        body = corrected.json()
        self.assertEqual(
            body["request_version"],
            submitted["version"] + 1,
        )
        self.assertEqual(body["line"]["raw_text"], raw_text)
        self.assertEqual(body["line"]["working_name"], "Мусорные пакеты 30 л")
        self.assertEqual(Decimal(body["line"]["quantity"]), Decimal("3"))
        self.assertEqual(body["line"]["requested_unit"]["code"], "ROLL")
        self.assertIsNone(body["line"]["product_id"])
        self.assertEqual(body["line"]["match_status"], "NEEDS_REVIEW")

        stale = self.client.patch(endpoint, json=payload)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            stale.json()["detail"]["code"],
            "SUPPLY_REQUEST_VERSION_CONFLICT",
        )

        allocated = self.client.put(
            f"/supply/requests/{created['id']}/lines/{line['id']}/allocations",
            json={
                "expected_version": body["request_version"],
                "allocations": [{
                    "action": "PURCHASE",
                    "planned_quantity": "3",
                    "unit_id": str(self.units["ROLL"].id),
                }],
            },
        )
        self.assertEqual(allocated.status_code, 200, allocated.text)
        self.assertTrue(allocated.json()["can_plan"])
        planned = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={"expected_version": allocated.json()["version"]},
        )
        self.assertEqual(planned.status_code, 200, planned.text)
        planned_body = planned.json()
        planned_line = planned_body["lines"][0]
        self.assertEqual(planned_body["status"], "PLANNED")
        self.assertIsNone(planned_line["product_id"])
        self.assertEqual(planned_line["planned_purchase"], "3.000")

        after_plan = self.client.patch(
            endpoint,
            json={
                **payload,
                "request_version": planned_body["version"],
                "requested_quantity": "4",
            },
        )
        self.assertEqual(after_plan.status_code, 409)
        self.assertEqual(
            after_plan.json()["detail"]["code"],
            "SUPPLY_REQUEST_NOT_EDITABLE",
        )

    def test_simple_send_preserves_request_and_creates_remainder_debt(
        self,
    ) -> None:
        raw_text = "Молоко 10 л"
        created = self.create_request(raw_text)
        self.assertEqual(self.recognize(created["id"]).status_code, 200)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        line = detail["lines"][0]
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()

        corrected = self.client.patch(
            (
                f"/supply/requests/{created['id']}/lines/{line['id']}"
                "/working-values"
            ),
            json={
                "request_version": submitted["version"],
                "working_name": "Молоко для крема",
                "requested_quantity": "10",
                "send_quantity": "8",
                "requested_unit_id": str(self.units["L"].id),
            },
        )
        self.assertEqual(corrected.status_code, 200, corrected.text)
        corrected_body = corrected.json()
        self.assertEqual(corrected_body["line"]["raw_text"], raw_text)
        self.assertEqual(corrected_body["line"]["parsed_name"], "Молоко")
        self.assertEqual(corrected_body["line"]["parsed_quantity"], "10.000")
        self.assertEqual(corrected_body["line"]["quantity"], "10.000")
        self.assertEqual(
            Decimal(corrected_body["line"]["send_quantity"]),
            Decimal("8"),
        )
        self.assertEqual(
            corrected_body["line"]["working_name"],
            "Молоко для крема",
        )
        immutable = self.client.patch(
            (
                f"/supply/requests/{created['id']}/lines/{line['id']}"
                "/working-values"
            ),
            json={
                "request_version": corrected_body["request_version"],
                "working_name": "Молоко для крема",
                "requested_quantity": "9",
                "send_quantity": "8",
                "requested_unit_id": str(self.units["L"].id),
            },
        )
        self.assertEqual(immutable.status_code, 409)
        self.assertEqual(
            immutable.json()["detail"]["code"],
            "SUPPLY_REQUESTED_QUANTITY_IMMUTABLE",
        )

        manual_draft = self.client.put(
            (
                f"/supply/requests/{created['id']}/lines/{line['id']}"
                "/allocations"
            ),
            json={
                "expected_version": corrected_body["request_version"],
                "allocations": [{
                    "action": "TRANSFER",
                    "planned_quantity": "2",
                    "unit_id": str(self.units["L"].id),
                }],
            },
        )
        self.assertEqual(manual_draft.status_code, 200, manual_draft.text)

        planned = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={
                "expected_version": manual_draft.json()["version"],
                "simple_mode": True,
            },
        )
        self.assertEqual(planned.status_code, 200, planned.text)
        planned_body = planned.json()
        planned_line = planned_body["lines"][0]
        self.assertEqual(planned_body["status"], "PARTIALLY_FULFILLED")
        self.assertEqual(Decimal(planned_line["planned_transfer"]), Decimal("0"))
        self.assertEqual(planned_line["planned_purchase"], "10.000")
        self.assertEqual(Decimal(planned_line["planned_cancel"]), Decimal("0"))
        self.assertEqual(planned_line["fulfilled_total"], "8.000")
        self.assertEqual(planned_line["unresolved_quantity"], "2.000")
        self.assertEqual(len(planned_line["allocations"]), 1)

        repeated = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={
                "expected_version": planned_body["version"],
                "simple_mode": True,
            },
        )
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(
            repeated.json()["detail"]["code"],
            "SUPPLY_REQUEST_NOT_EDITABLE",
        )
        fulfilled_line = self.client.get(
            f"/supply/requests/{created['id']}"
        ).json()["lines"][0]
        debt = self.client.get(
            f"/supply/debts/{fulfilled_line['active_debt_id']}"
        )
        self.assertEqual(debt.status_code, 200, debt.text)
        self.assertEqual(debt.json()["outstanding_quantity"], "2.000")
        debts = self.client.get("/supply/debts?status=ACTIVE").json()
        self.assertEqual(debts["total"], 1)

    def test_unmatched_simple_send_three_to_two_is_visible_everywhere(
        self,
    ) -> None:
        body = self._simple_send("Редкий ингредиент 3 кг", "2")
        line = body["lines"][0]
        self.assertIsNone(line["product_id"])
        self.assertEqual(body["status"], "PARTIALLY_FULFILLED")
        self.assertEqual(line["unresolved_quantity"], "1.000")
        self.assertIsNotNone(line["active_debt_id"])
        self.assertEqual(line["active_debt_quantity"], "1.000")

        debts = self.client.get(
            "/supply/debts",
            params={
                "status": "ACTIVE",
                "search": "Редкий ингредиент",
            },
        )
        self.assertEqual(debts.status_code, 200, debts.text)
        self.assertEqual(debts.json()["total"], 1)
        debt = debts.json()["items"][0]
        self.assertIsNone(debt["product"])
        self.assertEqual(debt["working_name"], "Редкий ингредиент")
        self.assertEqual(debt["outstanding_quantity"], "1.000")
        self.assertEqual(debt["department"]["id"], str(self.department.id))

        dashboard = self.client.get("/supply/summary/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertEqual(dashboard.json()["active_debts"], 1)

        repeated = self.client.post(
            f"/supply/requests/{body['id']}/plan",
            json={"expected_version": body["version"], "simple_mode": True},
        )
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(
            self.client.get("/supply/debts?status=ACTIVE").json()["total"],
            1,
        )

    def _simple_send(
        self,
        raw_text: str,
        send_quantity: str,
    ) -> dict:
        created = self.create_request(raw_text)
        self.assertEqual(self.recognize(created["id"]).status_code, 200)
        detail = self.client.get(
            f"/supply/requests/{created['id']}"
        ).json()
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()
        line = submitted["lines"][0]
        corrected = self.client.patch(
            (
                f"/supply/requests/{created['id']}/lines/{line['id']}"
                "/working-values"
            ),
            json={
                "request_version": submitted["version"],
                "working_name": line["working_name"],
                "send_quantity": send_quantity,
                "requested_unit_id": line["requested_unit"]["id"],
            },
        )
        self.assertEqual(corrected.status_code, 200, corrected.text)
        result = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={
                "expected_version": corrected.json()["request_version"],
                "simple_mode": True,
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_simple_send_above_request_fulfills_without_debt(self) -> None:
        body = self._simple_send("Молоко 50 л", "100")
        line = body["lines"][0]
        self.assertEqual(body["status"], "FULFILLED")
        self.assertEqual(line["quantity"], "50.000")
        self.assertEqual(line["send_quantity"], "100.000")
        self.assertEqual(line["fulfilled_total"], "100.000")
        self.assertEqual(Decimal(line["unresolved_quantity"]), Decimal("0"))
        self.assertIsNone(line["active_debt_id"])

        repeated = self.client.post(
            f"/supply/requests/{body['id']}/plan",
            json={
                "expected_version": body["version"],
                "simple_mode": True,
            },
        )
        self.assertEqual(repeated.status_code, 409)
        debts = self.client.get("/supply/debts?status=ACTIVE").json()
        self.assertEqual(debts["total"], 0)

    def test_simple_send_small_overage_fulfills_without_debt(self) -> None:
        body = self._simple_send("Молоко 10 л", "12")
        line = body["lines"][0]
        self.assertEqual(body["status"], "FULFILLED")
        self.assertEqual(line["fulfilled_total"], "12.000")
        self.assertEqual(Decimal(line["unresolved_quantity"]), Decimal("0"))
        self.assertIsNone(line["active_debt_id"])

    def test_simple_send_fractional_overage_fulfills_without_debt(
        self,
    ) -> None:
        body = self._simple_send("Молоко 2.5 л", "3.75")
        line = body["lines"][0]
        self.assertEqual(body["status"], "FULFILLED")
        self.assertEqual(line["fulfilled_total"], "3.750")
        self.assertEqual(Decimal(line["unresolved_quantity"]), Decimal("0"))
        self.assertIsNone(line["active_debt_id"])

    def test_simple_send_unmatched_overage_fulfills_without_debt(
        self,
    ) -> None:
        body = self._simple_send("Редкий крем 3 кг", "5")
        line = body["lines"][0]
        self.assertIsNone(line["product_id"])
        self.assertEqual(body["status"], "FULFILLED")
        self.assertEqual(line["fulfilled_total"], "5.000")
        self.assertEqual(Decimal(line["unresolved_quantity"]), Decimal("0"))
        self.assertIsNone(line["active_debt_id"])

    def test_simple_send_full_quantity_finishes_without_debt(self) -> None:
        created = self.create_request("Молоко 10 л")
        self.assertEqual(self.recognize(created["id"]).status_code, 200)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()

        result = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={
                "expected_version": submitted["version"],
                "simple_mode": True,
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["status"], "FULFILLED")
        self.assertEqual(body["lines"][0]["quantity"], "10.000")
        self.assertEqual(body["lines"][0]["send_quantity"], "10.000")
        self.assertEqual(body["lines"][0]["fulfilled_total"], "10.000")
        self.assertIsNone(body["lines"][0]["active_debt_id"])

    def test_simple_send_zero_creates_full_debt(self) -> None:
        created = self.create_request("Молоко 10 л")
        self.assertEqual(self.recognize(created["id"]).status_code, 200)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()
        line = submitted["lines"][0]
        corrected = self.client.patch(
            (
                f"/supply/requests/{created['id']}/lines/{line['id']}"
                "/working-values"
            ),
            json={
                "request_version": submitted["version"],
                "working_name": line["working_name"],
                "send_quantity": "0",
                "requested_unit_id": line["requested_unit"]["id"],
            },
        ).json()

        result = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={
                "expected_version": corrected["request_version"],
                "simple_mode": True,
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["status"], "PARTIALLY_FULFILLED")
        self.assertEqual(
            Decimal(body["lines"][0]["fulfilled_total"]),
            Decimal("0"),
        )
        debt = self.client.get(
            f"/supply/debts/{body['lines'][0]['active_debt_id']}"
        ).json()
        self.assertEqual(debt["outstanding_quantity"], "10.000")

    def test_simple_send_fractional_unmatched_line_uses_working_identity(
        self,
    ) -> None:
        created = self.create_request("Редкий крем 2.5 кг")
        self.assertEqual(self.recognize(created["id"]).status_code, 200)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        self.assertIsNone(detail["lines"][0]["product_id"])
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()
        line = submitted["lines"][0]
        corrected = self.client.patch(
            (
                f"/supply/requests/{created['id']}/lines/{line['id']}"
                "/working-values"
            ),
            json={
                "request_version": submitted["version"],
                "working_name": "Крем особый",
                "send_quantity": "1.5",
                "requested_unit_id": line["requested_unit"]["id"],
            },
        ).json()
        result = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={
                "expected_version": corrected["request_version"],
                "simple_mode": True,
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["lines"][0]["quantity"], "2.500")
        self.assertEqual(body["lines"][0]["fulfilled_total"], "1.500")
        debt = self.client.get(
            f"/supply/debts/{body['lines'][0]['active_debt_id']}"
        ).json()
        self.assertIsNone(debt["product"])
        self.assertEqual(debt["working_name"], "Крем особый")
        self.assertEqual(debt["unit"]["code"], "KG")
        self.assertEqual(debt["outstanding_quantity"], "1.000")

    def test_simple_send_can_change_before_finalization(self) -> None:
        created = self.create_request("Молоко 10 л")
        self.assertEqual(self.recognize(created["id"]).status_code, 200)
        detail = self.client.get(f"/supply/requests/{created['id']}").json()
        submitted = self.client.post(
            f"/supply/requests/{created['id']}/submit",
            json={"expected_version": detail["version"]},
        ).json()
        line = submitted["lines"][0]
        endpoint = (
            f"/supply/requests/{created['id']}/lines/{line['id']}"
            "/working-values"
        )
        base = {
            "working_name": line["working_name"],
            "requested_unit_id": line["requested_unit"]["id"],
        }
        first = self.client.patch(
            endpoint,
            json={
                **base,
                "request_version": submitted["version"],
                "send_quantity": "8",
            },
        ).json()
        second = self.client.patch(
            endpoint,
            json={
                **base,
                "request_version": first["request_version"],
                "send_quantity": "7",
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["line"]["quantity"], "10.000")
        self.assertEqual(
            Decimal(second.json()["line"]["send_quantity"]),
            Decimal("7"),
        )
        result = self.client.post(
            f"/supply/requests/{created['id']}/plan",
            json={
                "expected_version": second.json()["request_version"],
                "simple_mode": True,
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        result_line = result.json()["lines"][0]
        debt = self.client.get(
            f"/supply/debts/{result_line['active_debt_id']}"
        ).json()
        self.assertEqual(debt["outstanding_quantity"], "3.000")

    def test_registry_filters_summary_pagination_and_stable_status_order(self) -> None:
        submitted = self.create_request("неизвестная позиция 2 кг")
        self.assertEqual(self.recognize(submitted["id"]).status_code, 200)
        detail = self.client.get(f"/supply/requests/{submitted['id']}").json()
        self.assertEqual(
            self.client.post(
                f"/supply/requests/{submitted['id']}/submit",
                json={"expected_version": detail["version"]},
            ).status_code,
            200,
        )
        draft = self.create_request("Молоко 1 л")
        filtered = self.client.get(
            "/supply/requests",
            params={
                "search": submitted["public_number"],
                "department_id": str(self.department.id),
                "direction_id": str(self.direction.id),
                "status": "SUBMITTED",
                "has_needs_review": "true",
                "limit": 1,
                "offset": 0,
            },
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(len(filtered.json()), 1)
        self.assertEqual(filtered.json()[0]["lines_needs_review"], 1)
        ordered = self.client.get("/supply/requests?limit=100&offset=0").json()
        self.assertEqual(ordered[0]["id"], submitted["id"])
        self.assertIn(draft["id"], [item["id"] for item in ordered])

    def test_needs_review_filter_includes_unprocessed_and_parsed_only(self) -> None:
        unprocessed = self.create_request("Новая строка 1 кг")
        parsed = self.create_request("Разобранная строка 1 кг")
        matched = self.create_request("Молоко 1 л")
        rejected = self.create_request("Отклонённая строка 1 кг")
        with self.session_factory.begin() as session:
            parsed_line = session.get(
                SupplyRequestLine,
                UUID(parsed["lines"][0]["id"]),
            )
            parsed_line.match_status = "PARSED"
        self.assertEqual(self.recognize(matched["id"]).status_code, 200)
        reject_response = self.match(
            rejected["id"],
            rejected["lines"][0]["id"],
            {"action": "REJECT"},
        )
        self.assertEqual(reject_response.status_code, 200, reject_response.text)

        filtered = self.client.get(
            "/supply/requests",
            params={"has_needs_review": "true", "limit": 100},
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        items = {item["id"]: item for item in filtered.json()}
        self.assertIn(unprocessed["id"], items)
        self.assertIn(parsed["id"], items)
        self.assertNotIn(matched["id"], items)
        self.assertNotIn(rejected["id"], items)
        self.assertEqual(items[unprocessed["id"]]["lines_needs_review"], 1)
        self.assertEqual(items[parsed["id"]]["lines_needs_review"], 1)


if __name__ == "__main__":
    unittest.main()
