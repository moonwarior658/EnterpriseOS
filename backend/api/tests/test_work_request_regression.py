import os
import tempfile
import unittest

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.models.work_request import (
    WorkRequest,
    WorkRequestAttachment,
    WorkRequestComment,
)


WAREHOUSE_PAYLOAD = {
    "request_type": "warehouse",
    "department": "М15",
    "description": "Картофель 10 кг",
    "warehouse_category": "products",
}


class WorkRequestRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_upload_dir = settings.work_request_upload_dir
        settings.work_request_upload_dir = self.temp_dir.name
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
        WorkRequestAttachment.__table__.create(self.engine)
        WorkRequestComment.__table__.create(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        with self.session_factory.begin() as session:
            session.add(
                User(
                    id=1,
                    username="admin",
                    display_name="Администратор",
                    hashed_password="unused",
                    is_active=True,
                    is_admin=True,
                )
            )

        def override_get_db():
            with self.session_factory() as session:
                yield session

        def override_current_user():
            with self.session_factory() as session:
                return session.get(User, 1)

        self.override_current_user = override_current_user
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        settings.work_request_upload_dir = self.previous_upload_dir
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_existing_authenticated_post_requests_still_works(self) -> None:
        response = self.client.post("/requests", json=WAREHOUSE_PAYLOAD)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "new")
        self.assertEqual(response.json()["department"], "М15")

    def test_existing_public_post_requests_still_works_without_auth(self) -> None:
        app.dependency_overrides.pop(get_current_user)
        response = self.client.post(
            "/public/requests",
            json=WAREHOUSE_PAYLOAD,
        )
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            response.json()["created_by_name"],
            "Подразделение: М15",
        )

    def test_existing_protected_list_and_detail_routes_are_unchanged(self) -> None:
        created = self.client.post("/requests", json=WAREHOUSE_PAYLOAD).json()
        listed = self.client.get("/requests")
        detail = self.client.get(f"/requests/{created['id']}")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["id"], created["id"])
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["description"], "Картофель 10 кг")


if __name__ == "__main__":
    unittest.main()
