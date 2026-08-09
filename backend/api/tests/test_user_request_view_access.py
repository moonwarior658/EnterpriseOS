import os
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
from app.db.session import get_db
from app.main import app
from app.models.user import User


class UserRequestViewAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            session.add_all([
                User(
                    id=1,
                    username="admin",
                    display_name="Администратор",
                    hashed_password="unused",
                    is_active=True,
                    is_admin=True,
                    tenant_id="eclair",
                ),
                User(
                    id=2,
                    username="viewer",
                    display_name="Наблюдатель",
                    hashed_password="unused",
                    is_active=True,
                    is_admin=False,
                    can_view_requests=False,
                    tenant_id="eclair",
                ),
                User(
                    id=3,
                    username="foreign",
                    display_name="Чужой пользователь",
                    hashed_password="unused",
                    is_active=True,
                    is_admin=False,
                    can_view_requests=True,
                    tenant_id="other",
                ),
            ])
        self.current_user_id = 1

        def override_get_db():
            with self.sessions() as session:
                yield session

        def override_current_user():
            with self.sessions() as session:
                return session.get(User, self.current_user_id)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_admin_manages_only_users_in_own_tenant(self) -> None:
        listed = self.client.get("/users")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["id"] for item in listed.json()], [1, 2])
        self.assertEqual(self.client.get("/users/2").status_code, 200)
        self.assertEqual(self.client.get("/users/3").status_code, 404)
        self.assertEqual(
            self.client.patch(
                "/users/3", json={"can_view_requests": False}
            ).status_code,
            404,
        )

    def test_admin_assigns_and_removes_request_view_access(self) -> None:
        granted = self.client.patch(
            "/users/2", json={"can_view_requests": True}
        )
        self.assertEqual(granted.status_code, 200, granted.text)
        self.assertTrue(granted.json()["can_view_requests"])

        revoked = self.client.patch(
            "/users/2", json={"can_view_requests": False}
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertFalse(revoked.json()["can_view_requests"])

    def test_tenant_cannot_be_changed_through_user_payload(self) -> None:
        response = self.client.patch(
            "/users/2",
            json={"tenant_id": "other"},
        )
        self.assertEqual(response.status_code, 422, response.text)
        with self.sessions() as session:
            self.assertEqual(session.get(User, 2).tenant_id, "eclair")

        self.current_user_id = 2
        self.assertEqual(
            self.client.patch(
                "/users/2", json={"can_view_requests": True}
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
