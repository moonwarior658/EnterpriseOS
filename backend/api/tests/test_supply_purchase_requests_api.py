import os
import unittest
from datetime import date, timedelta
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.supply import (
    SupplyProduct,
    SupplyProductCategory,
    SupplyPurchaseRequest,
    SupplyPurchaseRequestLine,
    SupplyPurchaseRequestLineSource,
    SupplyUnit,
    SupplyRequestDirection,
    SupplyStorageZone,
)
from app.models.user import User


class SupplyPurchaseRequestsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine, "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        for table in (
            User.__table__, SupplyUnit.__table__, SupplyRequestDirection.__table__,
            SupplyProductCategory.__table__, SupplyStorageZone.__table__,
            SupplyProduct.__table__,
            SupplyPurchaseRequest.__table__, SupplyPurchaseRequestLine.__table__,
            SupplyPurchaseRequestLineSource.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            session.add_all([
                User(id=1, username="employee", display_name="Employee", hashed_password="x", tenant_id="eclair", is_active=True, is_admin=False),
                User(id=2, username="admin", display_name="Admin", hashed_password="x", tenant_id="eclair", is_active=True, is_admin=True),
                User(id=3, username="other", display_name="Other", hashed_password="x", tenant_id="other", is_active=True, is_admin=True),
            ])
            self.unit = SupplyUnit(tenant_id="eclair", code="KG", name_ru="Килограмм", short_name_ru="кг", allows_fraction=True, is_active=True)
            self.unit_two = SupplyUnit(tenant_id="eclair", code="BOX", name_ru="Коробка", short_name_ru="кор.", allows_fraction=False, is_active=True)
            self.other_unit = SupplyUnit(tenant_id="other", code="KG", name_ru="Килограмм", short_name_ru="кг", allows_fraction=True, is_active=True)
            session.add_all([self.unit, self.unit_two, self.other_unit])
            session.flush()
            self.product = SupplyProduct(tenant_id="eclair", name="Сахар", normalized_name="сахар", default_unit_id=self.unit.id, is_active=True)
            self.other_product = SupplyProduct(tenant_id="other", name="Сахар", normalized_name="сахар", default_unit_id=self.other_unit.id, is_active=True)
            session.add_all([self.product, self.other_product])
        self.current_user_id = 2

        def override_db():
            with self.sessions() as session:
                yield session

        def override_user():
            with self.sessions() as session:
                return session.get(User, self.current_user_id)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine.dispose()

    def create_request(self):
        response = self.client.post("/supply/purchase-requests", json={
            "need_date": (date.today() + timedelta(days=1)).isoformat(),
            "comment": " Закупка к выпуску ",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def add_line(self, request_id, **changes):
        payload = {
            "product_id": str(self.product.id), "quantity": "80.000",
            "unit_id": str(self.unit.id), "comment": " Основная потребность ",
        }
        payload.update(changes)
        return self.client.post(
            f"/supply/purchase-requests/{request_id}/lines", json=payload
        )

    def test_create_list_get_update_and_number(self) -> None:
        created = self.create_request()
        self.assertRegex(created["number"], r"^ZR-\d{8}-001$")
        self.assertEqual(created["status"], "DRAFT")
        self.assertEqual(created["comment"], "Закупка к выпуску")
        self.assertEqual(created["lines"], [])
        listed = self.client.get("/supply/purchase-requests")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["line_count"], 0)
        updated = self.client.patch(
            f"/supply/purchase-requests/{created['id']}",
            json={"comment": "Уточнено"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["comment"], "Уточнено")
        self.assertEqual(
            self.client.get(f"/supply/purchase-requests/{created['id']}").status_code,
            200,
        )

    def test_line_crud_sources_and_uniqueness(self) -> None:
        request_id = self.create_request()["id"]
        added = self.add_line(request_id)
        self.assertEqual(added.status_code, 201, added.text)
        line = added.json()["lines"][0]
        self.assertEqual(line["product"]["name"], "Сахар")
        self.assertEqual(line["sources"][0]["source_type"], "MANUAL_FUTURE")
        self.assertEqual(line["sources"][0]["quantity"], "80.000")
        self.assertEqual(line["sources"][0]["unit"]["short_name_ru"], "кг")
        self.assertEqual(self.add_line(request_id).status_code, 409)
        different_unit = self.add_line(request_id, unit_id=str(self.unit_two.id))
        self.assertEqual(different_unit.status_code, 201, different_unit.text)
        updated = self.client.patch(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}",
            json={"quantity": "90.000", "comment": "Исправлено"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        updated_line = next(
            item for item in updated.json()["lines"] if item["id"] == line["id"]
        )
        self.assertEqual(updated_line["sources"][0]["quantity"], "90.000")
        deleted = self.client.delete(
            f"/supply/purchase-requests/{request_id}/lines/{line['id']}"
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(len(deleted.json()["lines"]), 1)

    def test_ready_and_cancelled_are_read_only(self) -> None:
        request_id = self.create_request()["id"]
        self.assertEqual(self.add_line(request_id).status_code, 201)
        ready = self.client.post(f"/supply/purchase-requests/{request_id}/ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(ready.json()["status"], "READY")
        line_id = ready.json()["lines"][0]["id"]
        self.assertEqual(self.add_line(request_id).status_code, 409)
        self.assertEqual(self.client.patch(f"/supply/purchase-requests/{request_id}/lines/{line_id}", json={"quantity": "1"}).status_code, 409)
        self.assertEqual(self.client.delete(f"/supply/purchase-requests/{request_id}/lines/{line_id}").status_code, 409)
        cancelled = self.client.post(f"/supply/purchase-requests/{request_id}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        self.assertEqual(self.client.patch(f"/supply/purchase-requests/{request_id}", json={"comment": "x"}).status_code, 409)
        self.assertEqual(self.client.post(f"/supply/purchase-requests/{request_id}/cancel").status_code, 409)

    def test_validation_and_tenant_isolation(self) -> None:
        request_id = self.create_request()["id"]
        self.assertEqual(self.add_line(request_id, quantity="0").status_code, 422)
        self.assertEqual(self.add_line(request_id, product_id=str(self.other_product.id)).status_code, 404)
        self.assertEqual(self.add_line(request_id, unit_id=str(self.other_unit.id)).status_code, 404)
        self.current_user_id = 3
        self.assertEqual(self.client.get(f"/supply/purchase-requests/{request_id}").status_code, 404)
        self.assertEqual(self.client.get("/supply/purchase-requests").json()["items"], [])

    def test_admin_only_and_empty_ready(self) -> None:
        request_id = self.create_request()["id"]
        self.assertEqual(self.client.post(f"/supply/purchase-requests/{request_id}/ready").status_code, 409)
        self.current_user_id = 1
        for method, url, body in (
            ("get", "/supply/purchase-requests", None),
            ("post", "/supply/purchase-requests", {"need_date": date.today().isoformat()}),
            ("get", f"/supply/purchase-requests/{uuid4()}", None),
        ):
            self.assertEqual(self.client.request(method, url, json=body).status_code, 403)


if __name__ == "__main__":
    unittest.main()
