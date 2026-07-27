import os
import unittest
from datetime import datetime, timezone
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
    SupplyRequest,
    SupplyRequestDirection,
    SupplyRequestLine,
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
        SupplyUnit.__table__.create(self.engine)
        SupplyProductCategory.__table__.create(self.engine)
        SupplyStorageZone.__table__.create(self.engine)
        SupplyProduct.__table__.create(self.engine)
        SupplyProductAlias.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
        SupplyRequest.__table__.create(self.engine)
        SupplyRequestLine.__table__.create(self.engine)
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
        response = self.client.post(
            "/supply/requests",
            json={
                "department_id": str(self.department.id),
                "direction_id": str(self.direction.id),
                "raw_input": "\n".join(raw_lines),
                "lines": [{"raw_text": line} for line in raw_lines],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def recognize(self, request_id: str, *, force: bool = False):
        return self.client.post(
            f"/supply/requests/{request_id}/recognize",
            params={"force": str(force).lower()},
        )

    def match(self, request_id: str, line_id: str, payload: dict):
        return self.client.post(
            f"/supply/requests/{request_id}/lines/{line_id}/match",
            json=payload,
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
        created = self.create_request("Сливочки 2 л")
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
        self.assertEqual(body["parsed_name"], "Сливочки")

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
        self.assertEqual(body["parsed_name"], "Сливочки")
        self.assertEqual(body["raw_text"], "Сливочки 2 л")

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


if __name__ == "__main__":
    unittest.main()
