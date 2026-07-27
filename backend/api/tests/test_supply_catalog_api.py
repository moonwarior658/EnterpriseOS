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
from sqlalchemy import create_engine, event, select
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
from app.supply.service import (
    InvalidSupplyQuantityError,
    validate_quantity_for_unit,
)


UNIT_DATA = (
    ("KG", "килограмм", "кг", True),
    ("L", "литр", "л", True),
    ("PCS", "штука", "шт", False),
    ("PACK", "упаковка", "уп", False),
    ("BOX", "коробка", "кор", False),
)


class SupplyCatalogApiTests(unittest.TestCase):
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

    def product_payload(self, **changes) -> dict:
        payload = {
            "name": "Молоко 3,2%",
            "default_unit_id": str(self.units["L"].id),
            "request_direction_id": str(self.direction.id),
        }
        payload.update(changes)
        return payload

    def create_product(self, **changes) -> dict:
        response = self.client.post(
            "/supply/products",
            json=self.product_payload(**changes),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_category(self, **changes) -> dict:
        payload = {
            "code": "DAIRY",
            "name": "Молочная продукция",
            "description": "Основная категория",
            "sort_order": 10,
        }
        payload.update(changes)
        response = self.client.post(
            "/supply/product-categories",
            json=payload,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_zone(self, **changes) -> dict:
        payload = {
            "code": "REFRIGERATOR",
            "name": "Холодильник",
            "sort_order": 20,
        }
        payload.update(changes)
        response = self.client.post("/supply/storage-zones", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def request_payload(self, line: dict) -> dict:
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
        return {
            "department_id": str(self.department.id),
            "direction_id": str(self.direction.id),
            "cycle_id": str(cycle_id),
            "raw_input": line["raw_text"],
            "lines": [line],
        }

    def test_units_are_exact_admin_only_and_tenant_scoped(self) -> None:
        with self.session_factory.begin() as session:
            session.add(
                SupplyUnit(
                    tenant_id="other",
                    code="KG",
                    name_ru="скрытый килограмм",
                    short_name_ru="кг",
                    allows_fraction=True,
                )
            )

        response = self.client.get("/supply/units")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [
                (
                    item["code"],
                    item["short_name_ru"],
                    item["allows_fraction"],
                )
                for item in response.json()
            ],
            [
                ("BOX", "кор", False),
                ("KG", "кг", True),
                ("L", "л", True),
                ("PACK", "уп", False),
                ("PCS", "шт", False),
            ],
        )

        self.current_user_id = 1
        self.assertEqual(self.client.get("/supply/units").status_code, 403)
        app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.get("/supply/units").status_code, 401)

    def test_product_crud_normalizes_and_supports_nullable_direction(self) -> None:
        created = self.create_product(name="  Молоко   Ёлочка  ")
        self.assertEqual(created["name"], "Молоко   Ёлочка")
        self.assertEqual(created["default_unit"]["code"], "L")
        self.assertEqual(created["request_direction"]["code"], "MAIN")
        self.assertEqual(created["aliases"], [])

        with self.session_factory() as session:
            product = session.get(SupplyProduct, UUID(created["id"]))
            self.assertEqual(product.normalized_name, "молоко елочка")

        updated = self.client.patch(
            f"/supply/products/{created['id']}",
            json={
                "name": "Молоко питьевое",
                "default_unit_id": str(self.units["KG"].id),
                "request_direction_id": None,
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        body = updated.json()
        self.assertEqual(body["name"], "Молоко питьевое")
        self.assertEqual(body["default_unit"]["code"], "KG")
        self.assertIsNone(body["request_direction"])
        self.assertTrue(body["is_active"])
        archived = self.client.post(
            f"/supply/products/{created['id']}/archive"
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertFalse(archived.json()["is_active"])
        self.assertEqual(
            self.client.get(f"/supply/products/{created['id']}").status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(f"/supply/products/{created['id']}").status_code,
            405,
        )

    def test_duplicate_normalized_names_and_aliases_return_conflict(self) -> None:
        first = self.create_product(name="Ёжевика   замороженная")
        duplicate = self.client.post(
            "/supply/products",
            json=self.product_payload(name="  ЕЖЕВИКА замороженная  "),
        )
        self.assertEqual(duplicate.status_code, 409)

        alias = self.client.post(
            f"/supply/products/{first['id']}/aliases",
            json={"alias": "  Ягода   Ёжевика "},
        )
        self.assertEqual(alias.status_code, 201, alias.text)
        duplicate_alias = self.client.post(
            f"/supply/products/{first['id']}/aliases",
            json={"alias": "ягода ежевика"},
        )
        self.assertEqual(duplicate_alias.status_code, 409)

    def test_list_paginates_filters_and_searches_name_or_alias(self) -> None:
        milk = self.create_product(name="Молоко")
        sugar = self.create_product(
            name="Сахар",
            default_unit_id=str(self.units["KG"].id),
            request_direction_id=None,
        )
        self.client.post(
            f"/supply/products/{milk['id']}/aliases",
            json={"alias": "Молочко"},
        )
        self.client.post(f"/supply/products/{sugar['id']}/archive")

        page = self.client.get("/supply/products?limit=1&offset=1")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 2)
        self.assertEqual(len(page.json()["items"]), 1)
        self.assertEqual(page.json()["limit"], 1)
        self.assertEqual(page.json()["offset"], 1)

        active = self.client.get("/supply/products?active=true").json()
        inactive = self.client.get("/supply/products?active=false").json()
        alias_search = self.client.get(
            "/supply/products",
            params={"search": "  МОЛОЧКО "},
        ).json()
        self.assertEqual([item["id"] for item in active["items"]], [milk["id"]])
        self.assertEqual(
            [item["id"] for item in inactive["items"]],
            [sugar["id"]],
        )
        self.assertEqual(
            [item["id"] for item in alias_search["items"]],
            [milk["id"]],
        )
        self.assertEqual(
            self.client.get("/supply/products?limit=0").status_code,
            422,
        )

    def test_foreign_or_inactive_references_are_rejected_and_hidden(self) -> None:
        with self.session_factory.begin() as session:
            foreign_unit = SupplyUnit(
                tenant_id="other",
                code="L",
                name_ru="литр",
                short_name_ru="л",
                allows_fraction=True,
            )
            foreign_direction = SupplyRequestDirection(
                tenant_id="other",
                code="MAIN",
                name="Основной",
            )
            foreign_product = SupplyProduct(
                tenant_id="other",
                name="Скрытый товар",
                normalized_name="скрытый товар",
                default_unit=foreign_unit,
                request_direction=foreign_direction,
            )
            session.add_all(
                [foreign_unit, foreign_direction, foreign_product]
            )
            self.units["L"].is_active = False
            self.direction.is_active = False
            session.merge(self.units["L"])
            session.merge(self.direction)
            session.flush()
            foreign_product_id = foreign_product.id

        foreign_unit_response = self.client.post(
            "/supply/products",
            json=self.product_payload(
                default_unit_id=str(foreign_unit.id),
                request_direction_id=None,
            ),
        )
        inactive_unit_response = self.client.post(
            "/supply/products",
            json=self.product_payload(request_direction_id=None),
        )
        inactive_direction_response = self.client.post(
            "/supply/products",
            json=self.product_payload(
                default_unit_id=str(self.units["KG"].id),
            ),
        )
        self.assertEqual(foreign_unit_response.status_code, 422)
        self.assertEqual(inactive_unit_response.status_code, 422)
        self.assertEqual(inactive_direction_response.status_code, 422)
        self.assertEqual(
            self.client.get(
                f"/supply/products/{foreign_product_id}"
            ).status_code,
            404,
        )

    def test_alias_delete_is_scoped_and_missing_resources_are_404(self) -> None:
        product = self.create_product()
        alias = self.client.post(
            f"/supply/products/{product['id']}/aliases",
            json={"alias": "Молочко"},
        ).json()
        deleted = self.client.delete(
            f"/supply/products/{product['id']}/aliases/{alias['id']}"
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(
            self.client.delete(
                f"/supply/products/{product['id']}/aliases/{alias['id']}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"/supply/products/{uuid4()}/aliases",
                json={"alias": "Нет товара"},
            ).status_code,
            404,
        )

    def test_structured_lines_validate_quantity_and_preserve_original_text(
        self,
    ) -> None:
        product = self.create_product()
        original_text = "  Молоко 1,25 л  "
        fractional = self.client.post(
            "/supply/requests",
            json=self.request_payload(
                {
                    "raw_text": original_text,
                    "product_id": product["id"],
                    "requested_unit_id": str(self.units["L"].id),
                    "quantity": "1.250",
                }
            ),
        )
        self.assertEqual(fractional.status_code, 201, fractional.text)
        line = fractional.json()["lines"][0]
        self.assertEqual(line["raw_text"], original_text)
        self.assertEqual(line["product_id"], product["id"])
        self.assertEqual(line["requested_unit_id"], str(self.units["L"].id))
        self.assertEqual(Decimal(line["quantity"]), Decimal("1.250"))

        for code in ("PCS", "PACK", "BOX"):
            rejected = self.client.post(
                "/supply/requests",
                json=self.request_payload(
                    {
                        "raw_text": "Товар 1,5",
                        "requested_unit_id": str(self.units[code].id),
                        "quantity": "1.5",
                    }
                ),
            )
            self.assertEqual(rejected.status_code, 422, code)
            accepted = self.client.post(
                "/supply/requests",
                json=self.request_payload(
                    {
                        "raw_text": "Товар 2",
                        "requested_unit_id": str(self.units[code].id),
                        "quantity": "2",
                    }
                ),
            )
            self.assertEqual(accepted.status_code, 201, accepted.text)

        self.client.post(f"/supply/products/{product['id']}/archive")
        inactive_product = self.client.post(
            "/supply/requests",
            json=self.request_payload(
                {
                    "raw_text": "Неактивный товар 1 л",
                    "product_id": product["id"],
                    "requested_unit_id": str(self.units["L"].id),
                    "quantity": "1",
                }
            ),
        )
        self.assertEqual(inactive_product.status_code, 422)

        legacy = self.client.post(
            "/supply/requests",
            json=self.request_payload({"raw_text": "Свободная строка"}),
        )
        self.assertEqual(legacy.status_code, 201, legacy.text)
        legacy_line = legacy.json()["lines"][0]
        self.assertIsNone(legacy_line["product_id"])
        self.assertIsNone(legacy_line["requested_unit_id"])
        self.assertIsNone(legacy_line["quantity"])

    def test_product_endpoints_require_admin_and_authentication(self) -> None:
        self.current_user_id = 1
        forbidden = self.client.post(
            "/supply/products",
            json=self.product_payload(),
        )
        self.assertEqual(forbidden.status_code, 403)
        app.dependency_overrides.pop(get_current_user)
        unauthorized = self.client.get("/supply/products")
        self.assertEqual(unauthorized.status_code, 401)

    def test_reference_crud_normalization_pagination_and_tenant_scope(
        self,
    ) -> None:
        category = self.create_category(name="  Молочная   продукция  ")
        zone = self.create_zone()
        self.assertEqual(category["name"], "Молочная   продукция")
        self.assertEqual(zone["code"], "REFRIGERATOR")

        with self.session_factory() as session:
            stored = session.get(
                SupplyProductCategory,
                UUID(category["id"]),
            )
            self.assertEqual(
                stored.normalized_name,
                "молочная продукция",
            )

        duplicate_name = self.client.post(
            "/supply/product-categories",
            json={"code": "OTHER", "name": "МОЛОЧНАЯ продукция"},
        )
        duplicate_code = self.client.post(
            "/supply/storage-zones",
            json={"code": "REFRIGERATOR", "name": "Камера"},
        )
        self.assertEqual(duplicate_name.status_code, 409)
        self.assertEqual(duplicate_code.status_code, 409)

        updated = self.client.patch(
            f"/supply/product-categories/{category['id']}",
            json={"description": "  Обновлено  ", "sort_order": 5},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["description"], "Обновлено")
        page = self.client.get(
            "/supply/product-categories",
            params={"search": "молоч", "limit": 1, "offset": 0},
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 1)
        self.assertEqual(page.json()["items"][0]["id"], category["id"])

        with self.session_factory.begin() as session:
            foreign = SupplyProductCategory(
                tenant_id="other",
                code="FOREIGN",
                name="Чужая",
                normalized_name="чужая",
            )
            session.add(foreign)
            session.flush()
            foreign_id = foreign.id
        self.assertEqual(
            self.client.get(
                f"/supply/product-categories/{foreign_id}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                f"/supply/product-categories/{category['id']}"
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.delete(
                f"/supply/storage-zones/{zone['id']}"
            ).status_code,
            405,
        )

        self.current_user_id = 1
        self.assertEqual(
            self.client.get("/supply/product-categories").status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/supply/storage-zones").status_code,
            403,
        )
        app.dependency_overrides.pop(get_current_user)
        self.assertEqual(
            self.client.get("/supply/product-categories").status_code,
            401,
        )

    def test_product_card_iiko_search_and_reference_validation(self) -> None:
        category = self.create_category()
        zone = self.create_zone()
        created = self.create_product(
            iiko_id="  IIKO-MILK-001  ",
            category_id=category["id"],
            storage_zone_id=zone["id"],
        )
        self.assertEqual(created["iiko_id"], "IIKO-MILK-001")
        self.assertEqual(created["category"]["id"], category["id"])
        self.assertEqual(created["storage_zone"]["id"], zone["id"])
        self.assertIsNone(created["archived_at"])
        self.assertIsNone(created["archived_by_user_id"])

        search = self.client.get(
            "/supply/products",
            params={"search": "MILK-00"},
        )
        self.assertEqual(search.status_code, 200, search.text)
        self.assertEqual(
            [item["id"] for item in search.json()["items"]],
            [created["id"]],
        )
        duplicate = self.client.post(
            "/supply/products",
            json=self.product_payload(
                name="Другой товар",
                iiko_id="IIKO-MILK-001",
            ),
        )
        self.assertEqual(duplicate.status_code, 409)

        blank = self.create_product(
            name="Товар без iiko",
            iiko_id="   ",
            request_direction_id=None,
        )
        self.assertIsNone(blank["iiko_id"])
        cleared = self.client.patch(
            f"/supply/products/{created['id']}",
            json={"iiko_id": ""},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["iiko_id"])

        self.client.patch(
            f"/supply/product-categories/{category['id']}",
            json={"is_active": False},
        )
        inactive = self.client.patch(
            f"/supply/products/{created['id']}",
            json={"category_id": category["id"]},
        )
        self.assertEqual(inactive.status_code, 409)
        missing = self.client.patch(
            f"/supply/products/{created['id']}",
            json={"storage_zone_id": str(uuid4())},
        )
        self.assertEqual(missing.status_code, 404)
        with self.session_factory.begin() as session:
            foreign_category = SupplyProductCategory(
                tenant_id="other",
                code="DAIRY",
                name="Чужая категория",
                normalized_name="чужая категория",
            )
            foreign_zone = SupplyStorageZone(
                tenant_id="other",
                code="REFRIGERATOR",
                name="Чужая зона",
                normalized_name="чужая зона",
            )
            session.add_all([foreign_category, foreign_zone])
            session.flush()
            foreign_category_id = foreign_category.id
            foreign_zone_id = foreign_zone.id
        self.assertEqual(
            self.client.patch(
                f"/supply/products/{created['id']}",
                json={"category_id": str(foreign_category_id)},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f"/supply/products/{created['id']}",
                json={"storage_zone_id": str(foreign_zone_id)},
            ).status_code,
            404,
        )

    def test_archive_restore_is_idempotent_and_checks_references(self) -> None:
        category = self.create_category()
        zone = self.create_zone()
        product = self.create_product(
            category_id=category["id"],
            storage_zone_id=zone["id"],
        )
        alias = self.client.post(
            f"/supply/products/{product['id']}/aliases",
            json={"alias": "Молочко"},
        )
        self.assertEqual(alias.status_code, 201, alias.text)

        archived = self.client.post(
            f"/supply/products/{product['id']}/archive"
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        first = archived.json()
        self.assertFalse(first["is_active"])
        self.assertIsNotNone(first["archived_at"])
        self.assertEqual(first["archived_by_user_id"], 2)
        self.assertEqual(len(first["aliases"]), 1)
        repeated = self.client.post(
            f"/supply/products/{product['id']}/archive"
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(
            repeated.json()["archived_at"],
            first["archived_at"],
        )

        self.client.patch(
            f"/supply/storage-zones/{zone['id']}",
            json={"is_active": False},
        )
        blocked = self.client.post(
            f"/supply/products/{product['id']}/restore"
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertFalse(
            self.client.get(
                f"/supply/products/{product['id']}"
            ).json()["is_active"]
        )
        self.client.patch(
            f"/supply/storage-zones/{zone['id']}",
            json={"is_active": True},
        )
        restored = self.client.post(
            f"/supply/products/{product['id']}/restore"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertTrue(restored.json()["is_active"])
        self.assertIsNone(restored.json()["archived_at"])
        self.assertIsNone(restored.json()["archived_by_user_id"])
        repeated_restore = self.client.post(
            f"/supply/products/{product['id']}/restore"
        )
        self.assertEqual(repeated_restore.status_code, 200)

    def test_validation_statuses_are_strict(self) -> None:
        self.assertEqual(
            self.client.post(
                "/supply/products",
                json=self.product_payload(name="   "),
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(f"/supply/products/{uuid4()}").status_code,
            404,
        )
        product = self.create_product()
        self.assertEqual(
            self.client.patch(
                f"/supply/products/{product['id']}",
                json={"default_unit_id": None},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.patch(
                f"/supply/products/{product['id']}",
                json={"is_active": False},
            ).status_code,
            422,
        )


class SupplyCatalogValidationTests(unittest.TestCase):
    def test_normalization_is_central_and_deterministic(self) -> None:
        self.assertEqual(
            normalize_product_text("  СЫР   Ёлочка\t50%  "),
            "сыр елочка 50%",
        )

    def test_quantity_validation_uses_unit_fraction_policy(self) -> None:
        fractional = SupplyUnit(
            tenant_id="eclair",
            code="KG",
            name_ru="килограмм",
            short_name_ru="кг",
            allows_fraction=True,
        )
        integer = SupplyUnit(
            tenant_id="eclair",
            code="PCS",
            name_ru="штука",
            short_name_ru="шт",
            allows_fraction=False,
        )
        validate_quantity_for_unit(Decimal("1.25"), fractional)
        validate_quantity_for_unit(Decimal("2.000"), integer)
        with self.assertRaises(InvalidSupplyQuantityError):
            validate_quantity_for_unit(Decimal("1.25"), integer)


if __name__ == "__main__":
    unittest.main()
