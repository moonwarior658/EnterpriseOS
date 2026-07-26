import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.models.work_request import WorkRequest


WAREHOUSE_PAYLOAD = {
    "request_type": "warehouse",
    "department": "Производство",
    "description": "Картофель 10 кг",
    "warehouse_category": "products",
}

REPAIR_PAYLOAD = {
    "request_type": "repair",
    "department": "Кафе",
    "description": "Не включается кофемашина",
    "repair_category": "Кофемашина",
    "priority": "urgent",
}


class WorkRequestsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
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

        self.current_user_id = 1

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

    def create_warehouse_request(self) -> dict:
        response = self.client.post("/requests", json=WAREHOUSE_PAYLOAD)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_creates_warehouse_request_for_current_user(self) -> None:
        body = self.create_warehouse_request()

        self.assertEqual(body["request_type"], "warehouse")
        self.assertEqual(body["warehouse_category"], "products")
        self.assertIsNone(body["repair_category"])
        self.assertIsNone(body["priority"])
        self.assertEqual(body["status"], "new")
        self.assertEqual(body["created_by_name"], "Сотрудник")

    def test_creates_repair_request(self) -> None:
        response = self.client.post("/requests", json=REPAIR_PAYLOAD)

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["request_type"], "repair")
        self.assertEqual(body["repair_category"], "Кофемашина")
        self.assertEqual(body["priority"], "urgent")
        self.assertIsNone(body["warehouse_category"])

    def test_rejects_unknown_request_type(self) -> None:
        response = self.client.post(
            "/requests",
            json={**WAREHOUSE_PAYLOAD, "request_type": "purchase"},
        )

        self.assertEqual(response.status_code, 422)

    def test_rejects_wrong_category(self) -> None:
        response = self.client.post(
            "/requests",
            json={**WAREHOUSE_PAYLOAD, "warehouse_category": "equipment"},
        )

        self.assertEqual(response.status_code, 422)

    def test_rejects_empty_description(self) -> None:
        response = self.client.post(
            "/requests",
            json={**WAREHOUSE_PAYLOAD, "description": "   "},
        )

        self.assertEqual(response.status_code, 422)

    def test_lists_requests_newest_first(self) -> None:
        with self.session_factory.begin() as session:
            session.add_all(
                [
                    WorkRequest(
                        request_type="warehouse",
                        department="М15",
                        description="Старая заявка",
                        status="new",
                        warehouse_category="packaging",
                        created_by_user_id=1,
                        created_at=datetime(
                            2026, 7, 25, 8, 0, tzinfo=timezone.utc
                        ),
                    ),
                    WorkRequest(
                        request_type="repair",
                        department="М35",
                        description="Новая заявка",
                        status="new",
                        repair_category="Интернет",
                        priority="important",
                        created_by_user_id=2,
                        created_at=datetime(
                            2026, 7, 26, 8, 0, tzinfo=timezone.utc
                        ),
                    ),
                ]
            )

        response = self.client.get("/requests")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            [item["description"] for item in body],
            ["Новая заявка", "Старая заявка"],
        )
        self.assertEqual(body[0]["created_by_name"], "Администратор")

    def test_regular_user_cannot_change_status(self) -> None:
        request_id = self.create_warehouse_request()["id"]

        response = self.client.patch(
            f"/requests/{request_id}/status",
            json={"status": "in_progress"},
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_can_change_status(self) -> None:
        request_id = self.create_warehouse_request()["id"]
        self.current_user_id = 2

        response = self.client.patch(
            f"/requests/{request_id}/status",
            json={"status": "completed"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")

    def test_missing_request_returns_404(self) -> None:
        self.current_user_id = 2

        response = self.client.patch(
            "/requests/999/status",
            json={"status": "completed"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Request not found"})


if __name__ == "__main__":
    unittest.main()
