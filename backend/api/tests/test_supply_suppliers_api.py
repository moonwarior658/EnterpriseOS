import os
import unittest
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
from app.models.supply import SupplySupplier
from app.models.user import User


class SupplySuppliersApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
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
        User.__table__.create(self.engine)
        SupplySupplier.__table__.create(self.engine)
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
                        tenant_id="eclair",
                        is_active=True,
                        is_admin=False,
                    ),
                    User(
                        id=2,
                        username="admin",
                        display_name="Администратор",
                        hashed_password="unused",
                        tenant_id="eclair",
                        is_active=True,
                        is_admin=True,
                    ),
                    User(
                        id=3,
                        username="other-admin",
                        display_name="Другой администратор",
                        hashed_password="unused",
                        tenant_id="other",
                        is_active=True,
                        is_admin=True,
                    ),
                ]
            )
        self.current_user_id = 2

        def override_get_db():
            with self.session_factory() as session:
                yield session

        def override_current_user():
            with self.session_factory() as session:
                return session.get(User, self.current_user_id)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine.dispose()

    @staticmethod
    def supplier_payload(**changes) -> dict:
        payload = {
            "display_name": "  Новопак  ",
            "legal_name": " ООО Новопак ",
            "inn": "6671000001",
            "kpp": "667101001",
            "ogrn": "1026600000001",
            "legal_address": " Екатеринбург ",
            "actual_address": " Екатеринбург, склад ",
            "bank_name": " Банк ",
            "bik": "046577000",
            "correspondent_account": "30101810000000000000",
            "settlement_account": "40702810000000000000",
            "order_email": " orders@example.test ",
            "phone": " +7 900 000-00-00 ",
            "comment": " Основной поставщик упаковки ",
        }
        payload.update(changes)
        return payload

    def create_supplier(self, **changes) -> dict:
        response = self.client.post(
            "/supply/suppliers",
            json=self.supplier_payload(**changes),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_get_list_and_update_supplier(self) -> None:
        created = self.create_supplier()
        self.assertEqual(created["display_name"], "Новопак")
        self.assertEqual(created["legal_name"], "ООО Новопак")
        self.assertIsNone(created["minimum_order_amount"])
        self.assertTrue(created["is_active"])

        detail = self.client.get(f"/supply/suppliers/{created['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["inn"], "6671000001")

        listed = self.client.get("/supply/suppliers", params={"active": True})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(listed.json()["items"][0]["id"], created["id"])

        updated = self.client.patch(
            f"/supply/suppliers/{created['id']}",
            json={"display_name": " Рестоэксперт ", "comment": "  "},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["display_name"], "Рестоэксперт")
        self.assertIsNone(updated.json()["comment"])
        invalid = self.client.patch(
            f"/supply/suppliers/{created['id']}",
            json={"display_name": None},
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)
        invalid_email = self.client.patch(
            f"/supply/suppliers/{created['id']}",
            json={"order_email": "not-an-email"},
        )
        self.assertEqual(invalid_email.status_code, 422, invalid_email.text)

    def test_create_update_clear_and_validate_minimum_order_amount(self) -> None:
        created = self.create_supplier(
            inn="6671000002", minimum_order_amount="10000.25"
        )
        self.assertEqual(created["minimum_order_amount"], "10000.25")

        updated = self.client.patch(
            f"/supply/suppliers/{created['id']}",
            json={"minimum_order_amount": "12500.50"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["minimum_order_amount"], "12500.50")

        cleared = self.client.patch(
            f"/supply/suppliers/{created['id']}",
            json={"minimum_order_amount": None},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["minimum_order_amount"])

        negative = self.client.patch(
            f"/supply/suppliers/{created['id']}",
            json={"minimum_order_amount": "-0.01"},
        )
        self.assertEqual(negative.status_code, 422, negative.text)

    def test_archive_restore_and_active_only_list(self) -> None:
        created = self.create_supplier()
        archived = self.client.post(
            f"/supply/suppliers/{created['id']}/archive"
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertFalse(archived.json()["is_active"])
        self.assertIsNotNone(archived.json()["archived_at"])
        self.assertEqual(archived.json()["archived_by_user_id"], 2)

        active = self.client.get("/supply/suppliers", params={"active": True})
        self.assertEqual(active.status_code, 200, active.text)
        self.assertEqual(active.json()["items"], [])

        restored = self.client.post(
            f"/supply/suppliers/{created['id']}/restore"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertTrue(restored.json()["is_active"])
        self.assertIsNone(restored.json()["archived_at"])
        self.assertIsNone(restored.json()["archived_by_user_id"])

    def test_duplicate_inn_is_tenant_scoped_and_restore_is_guarded(self) -> None:
        original = self.create_supplier()
        duplicate = self.client.post(
            "/supply/suppliers",
            json=self.supplier_payload(display_name="Дубликат"),
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        self.current_user_id = 3
        other = self.create_supplier(display_name="Поставщик другого tenant")
        self.assertEqual(other["inn"], original["inn"])

        self.current_user_id = 2
        self.assertEqual(
            self.client.post(
                f"/supply/suppliers/{original['id']}/archive"
            ).status_code,
            200,
        )
        replacement = self.create_supplier(display_name="Новый Новопак")
        conflict = self.client.post(
            f"/supply/suppliers/{original['id']}/restore"
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertNotEqual(replacement["id"], original["id"])

    def test_tenant_isolation_hides_and_protects_foreign_supplier(self) -> None:
        own = self.create_supplier()
        self.current_user_id = 3

        self.assertEqual(
            self.client.get(f"/supply/suppliers/{own['id']}").status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f"/supply/suppliers/{own['id']}",
                json={"display_name": "Чужое изменение"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"/supply/suppliers/{own['id']}/archive"
            ).status_code,
            404,
        )
        listed = self.client.get("/supply/suppliers")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"], [])

    def test_supplier_api_is_admin_only(self) -> None:
        self.current_user_id = 1
        requests = (
            ("get", "/supply/suppliers", None),
            ("get", f"/supply/suppliers/{uuid4()}", None),
            ("post", "/supply/suppliers", self.supplier_payload()),
            ("patch", f"/supply/suppliers/{uuid4()}", {"phone": "1"}),
            ("post", f"/supply/suppliers/{uuid4()}/archive", None),
            ("post", f"/supply/suppliers/{uuid4()}/restore", None),
        )
        for method, url, payload in requests:
            response = self.client.request(method, url, json=payload)
            self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
