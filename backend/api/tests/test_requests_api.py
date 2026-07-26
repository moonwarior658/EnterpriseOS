import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic.config import Config
from alembic.script import ScriptDirectory
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
from app.schemas.work_request import DEPARTMENTS


WAREHOUSE_PAYLOAD = {
    "request_type": "warehouse",
    "department": "М15",
    "description": "Картофель 10 кг",
    "warehouse_category": "products",
}

REPAIR_PAYLOAD = {
    "request_type": "repair",
    "department": "Бар ГХ",
    "description": "Не включается кофемашина",
    "repair_category": "Кофемашина",
    "priority": "urgent",
}

PUBLIC_WAREHOUSE_PAYLOAD = {**WAREHOUSE_PAYLOAD}


class WorkRequestsApiTests(unittest.TestCase):
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

    def create_warehouse_request(self) -> dict:
        response = self.client.post("/requests", json=WAREHOUSE_PAYLOAD)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_public_repair(self, files: list[tuple] | None = None) -> dict:
        response = self.client.post(
            "/public/requests",
            data=REPAIR_PAYLOAD,
            files=files,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_creates_warehouse_request_for_current_user(self) -> None:
        body = self.create_warehouse_request()
        self.assertEqual(body["request_type"], "warehouse")
        self.assertEqual(body["warehouse_category"], "products")
        self.assertEqual(body["status"], "new")
        self.assertEqual(body["created_by_name"], "Сотрудник")
        self.assertEqual(body["attachment_count"], 0)

    def test_creates_repair_request(self) -> None:
        response = self.client.post("/requests", json=REPAIR_PAYLOAD)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["request_type"], "repair")
        self.assertEqual(body["priority"], "urgent")

    def test_public_warehouse_creation_needs_no_jwt_or_author_name(self) -> None:
        app.dependency_overrides.pop(get_current_user)
        response = self.client.post(
            "/public/requests",
            json=PUBLIC_WAREHOUSE_PAYLOAD,
        )
        app.dependency_overrides[get_current_user] = self.override_current_user

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            response.json()["created_by_name"],
            "Подразделение: М15",
        )
        with self.session_factory() as session:
            stored = session.get(WorkRequest, response.json()["id"])
            self.assertIsNone(stored.created_by_user_id)
            self.assertIsNone(stored.author_name)

    def test_public_repair_creation_needs_no_jwt(self) -> None:
        app.dependency_overrides.pop(get_current_user)
        response = self.client.post(
            "/public/requests",
            data=REPAIR_PAYLOAD,
        )
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["request_type"], "repair")

    def test_public_api_is_create_only_and_protected_reads_need_jwt(self) -> None:
        request_id = self.create_warehouse_request()["id"]
        app.dependency_overrides.pop(get_current_user)
        public_list = self.client.get("/public/requests")
        protected_list = self.client.get("/requests")
        protected_detail = self.client.get(f"/requests/{request_id}")
        app.dependency_overrides[get_current_user] = self.override_current_user

        self.assertEqual(public_list.status_code, 405)
        self.assertEqual(protected_list.status_code, 401)
        self.assertEqual(protected_detail.status_code, 401)

    def test_department_list_is_exact(self) -> None:
        self.assertEqual(
            DEPARTMENTS,
            {"М15", "М35", "М6А", "Цех ГХ", "Бар ГХ", "Кухня", "Авто"},
        )
        for department in DEPARTMENTS:
            response = self.client.post(
                "/public/requests",
                json={**PUBLIC_WAREHOUSE_PAYLOAD, "department": department},
            )
            self.assertEqual(response.status_code, 201, department)

    def test_rejects_legacy_or_unknown_department(self) -> None:
        for department in ("Производство", "М6а", "Неизвестно"):
            response = self.client.post(
                "/public/requests",
                json={**PUBLIC_WAREHOUSE_PAYLOAD, "department": department},
            )
            self.assertEqual(response.status_code, 422, department)

    def test_rejects_unknown_request_type_and_empty_description(self) -> None:
        wrong_type = self.client.post(
            "/requests",
            json={**WAREHOUSE_PAYLOAD, "request_type": "purchase"},
        )
        empty = self.client.post(
            "/requests",
            json={**WAREHOUSE_PAYLOAD, "description": "   "},
        )
        self.assertEqual(wrong_type.status_code, 422)
        self.assertEqual(empty.status_code, 422)

    def test_lists_requests_newest_first_and_serializes_legacy_author(self) -> None:
        with self.session_factory.begin() as session:
            session.add_all(
                [
                    WorkRequest(
                        request_type="warehouse",
                        department="Производство",
                        description="Старая заявка",
                        status="new",
                        warehouse_category="packaging",
                        created_by_user_id=None,
                        author_name="Иван",
                        created_at=datetime(2026, 7, 25, 8, tzinfo=timezone.utc),
                    ),
                    WorkRequest(
                        request_type="repair",
                        department="М35",
                        description="Новая заявка",
                        status="new",
                        repair_category="Интернет",
                        priority="important",
                        created_by_user_id=2,
                        created_at=datetime(2026, 7, 26, 8, tzinfo=timezone.utc),
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
        self.assertEqual(body[1]["created_by_name"], "Иван")

    def test_list_disables_cache_and_accepts_cache_buster(self) -> None:
        request_id = self.create_warehouse_request()["id"]

        response = self.client.get("/requests?_ts=123456789")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()], [request_id])
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertEqual(response.headers["expires"], "0")

    def test_gets_one_request_and_missing_returns_404(self) -> None:
        request_id = self.create_warehouse_request()["id"]
        found = self.client.get(f"/requests/{request_id}")
        missing = self.client.get("/requests/999")
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()["id"], request_id)
        self.assertEqual(missing.status_code, 404)

    def test_regular_user_cannot_edit_request(self) -> None:
        request_id = self.create_warehouse_request()["id"]
        response = self.client.patch(
            f"/requests/{request_id}",
            json={"description": "Изменено"},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_edit_request_and_status(self) -> None:
        request_id = self.create_warehouse_request()["id"]
        self.current_user_id = 2
        response = self.client.patch(
            f"/requests/{request_id}",
            json={
                "department": "Кухня",
                "description": "Молоко 5 л",
                "warehouse_category": "products",
                "status": "in_progress",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["department"], "Кухня")
        self.assertEqual(response.json()["status"], "in_progress")

    def test_request_type_cannot_be_changed(self) -> None:
        request_id = self.create_warehouse_request()["id"]
        self.current_user_id = 2
        response = self.client.patch(
            f"/requests/{request_id}",
            json={"request_type": "repair"},
        )
        self.assertEqual(response.status_code, 422)

    def test_existing_status_endpoint_remains_compatible(self) -> None:
        request_id = self.create_warehouse_request()["id"]
        self.current_user_id = 2
        response = self.client.patch(
            f"/requests/{request_id}/status",
            json={"status": "completed"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")

    def test_status_endpoint_updates_legacy_department_request(self) -> None:
        with self.session_factory.begin() as session:
            legacy = WorkRequest(
                request_type="warehouse",
                department="Производство",
                description="Историческая заявка",
                status="new",
                warehouse_category="products",
                created_by_user_id=1,
            )
            session.add(legacy)
            session.flush()
            request_id = legacy.id
        self.current_user_id = 2

        response = self.client.patch(
            f"/requests/{request_id}/status",
            json={"status": "in_progress"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["department"], "Производство")
        self.assertEqual(response.json()["status"], "in_progress")

    def test_admin_adds_comment_to_repair_request(self) -> None:
        request_id = self.create_public_repair()["id"]
        self.current_user_id = 2
        created = self.client.post(
            f"/requests/{request_id}/comments",
            json={"body": "Проверили питание"},
        )
        listed = self.client.get(f"/requests/{request_id}/comments")
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["author_name"], "Администратор")
        self.assertEqual(listed.json()[0]["body"], "Проверили питание")

    def test_regular_user_cannot_add_comment(self) -> None:
        request_id = self.create_public_repair()["id"]
        response = self.client.post(
            f"/requests/{request_id}/comments",
            json={"body": "Комментарий"},
        )
        self.assertEqual(response.status_code, 403)

    def test_comment_cannot_be_added_to_warehouse_request(self) -> None:
        request_id = self.create_warehouse_request()["id"]
        self.current_user_id = 2
        response = self.client.post(
            f"/requests/{request_id}/comments",
            json={"body": "Комментарий"},
        )
        self.assertEqual(response.status_code, 400)

    def test_uploads_valid_photo_and_links_it_to_request(self) -> None:
        body = self.create_public_repair(
            [("photos", ("machine.png", b"png-bytes", "image/png"))]
        )
        self.assertEqual(body["attachment_count"], 1)
        attachment = body["attachments"][0]
        with self.session_factory() as session:
            stored = session.get(WorkRequestAttachment, attachment["id"])
            self.assertEqual(stored.work_request_id, body["id"])
            self.assertTrue(
                (Path(self.temp_dir.name) / stored.stored_filename).is_file()
            )

    def test_rejects_invalid_mime_type(self) -> None:
        response = self.client.post(
            "/public/requests",
            data=REPAIR_PAYLOAD,
            files=[("photos", ("note.txt", b"text", "text/plain"))],
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_oversized_photo(self) -> None:
        response = self.client.post(
            "/public/requests",
            data=REPAIR_PAYLOAD,
            files=[
                (
                    "photos",
                    ("large.jpg", b"x" * (8 * 1024 * 1024 + 1), "image/jpeg"),
                )
            ],
        )
        self.assertEqual(response.status_code, 413)

    def test_rejects_more_than_five_photos(self) -> None:
        files = [
            ("photos", (f"{index}.webp", b"photo", "image/webp"))
            for index in range(6)
        ]
        response = self.client.post(
            "/public/requests",
            data=REPAIR_PAYLOAD,
            files=files,
        )
        self.assertEqual(response.status_code, 422)

    def test_attachment_requires_auth_and_authorized_user_can_read(self) -> None:
        body = self.create_public_repair(
            [("photos", ("machine.jpg", b"jpeg-bytes", "image/jpeg"))]
        )
        attachment_id = body["attachments"][0]["id"]
        path = f"/requests/{body['id']}/attachments/{attachment_id}"

        authorized = self.client.get(path)
        app.dependency_overrides.pop(get_current_user)
        unauthorized = self.client.get(path)
        app.dependency_overrides[get_current_user] = self.override_current_user

        self.assertEqual(authorized.status_code, 200, authorized.text)
        self.assertEqual(authorized.content, b"jpeg-bytes")
        self.assertEqual(unauthorized.status_code, 401)

    def test_migrations_have_single_head(self) -> None:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        self.assertEqual(script.get_heads(), ["20260726_0006"])


if __name__ == "__main__":
    unittest.main()
