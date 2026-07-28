import os
import tempfile
import unittest
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


REPAIR_PAYLOAD = {
    "request_type": "repair",
    "department": "Бар ГХ",
    "description": "Не включается кофемашина",
    "repair_category": "Кофемашина",
    "priority": "urgent",
}

WAREHOUSE_PAYLOAD = {
    "request_type": "warehouse",
    "department": "М15",
    "description": "Картофель 10 кг",
    "warehouse_category": "products",
}


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
            session.add_all([
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
            ])
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

    def create_repair(self) -> dict:
        response = self.client.post("/requests", json=REPAIR_PAYLOAD)
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

    def test_creates_repair_and_public_repair_without_jwt(self) -> None:
        authenticated = self.create_repair()
        self.assertEqual(authenticated["request_type"], "repair")
        self.assertEqual(authenticated["created_by_name"], "Сотрудник")

        app.dependency_overrides.pop(get_current_user)
        public = self.client.post("/public/requests", data=REPAIR_PAYLOAD)
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.assertEqual(public.status_code, 201, public.text)
        self.assertEqual(
            public.json()["created_by_name"],
            "Подразделение: Бар ГХ",
        )

    def test_warehouse_creation_is_removed(self) -> None:
        self.assertEqual(
            self.client.post("/requests", json=WAREHOUSE_PAYLOAD).status_code,
            422,
        )
        app.dependency_overrides.pop(get_current_user)
        response = self.client.post(
            "/public/requests",
            json=WAREHOUSE_PAYLOAD,
        )
        app.dependency_overrides[get_current_user] = self.override_current_user
        self.assertEqual(response.status_code, 422)

    def test_historical_warehouse_rows_are_archived_from_active_api(self) -> None:
        with self.session_factory.begin() as session:
            archived = WorkRequest(
                request_type="warehouse",
                department="М15",
                description="Архив склада",
                status="new",
                warehouse_category="products",
                created_by_user_id=1,
            )
            session.add(archived)
            session.flush()
            archived_id = archived.id
        repair = self.create_repair()

        listed = self.client.get("/requests")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json()], [repair["id"]])
        self.assertEqual(
            self.client.get(f"/requests/{archived_id}").status_code,
            404,
        )

    def test_list_cache_headers_and_authentication(self) -> None:
        self.create_repair()
        response = self.client.get("/requests?_ts=123")
        self.assertEqual(response.headers["cache-control"], (
            "no-store, no-cache, must-revalidate, max-age=0"
        ))
        app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.get("/requests").status_code, 401)
        app.dependency_overrides[get_current_user] = self.override_current_user

    def test_admin_updates_all_repair_fields_and_status(self) -> None:
        request_id = self.create_repair()["id"]
        self.current_user_id = 2
        response = self.client.patch(
            f"/requests/{request_id}",
            json={
                "department": "Авто",
                "description": "Новая формулировка",
                "repair_category": "Другое",
                "priority": "important",
                "status": "in_progress",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["department"], "Авто")
        self.assertEqual(response.json()["status"], "in_progress")

    def test_regular_user_cannot_edit_or_comment(self) -> None:
        request_id = self.create_repair()["id"]
        self.assertEqual(
            self.client.patch(
                f"/requests/{request_id}",
                json={"status": "completed"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/requests/{request_id}/comments",
                json={"body": "Комментарий"},
            ).status_code,
            403,
        )

    def test_admin_adds_and_reads_repair_comment(self) -> None:
        request_id = self.create_repair()["id"]
        self.current_user_id = 2
        created = self.client.post(
            f"/requests/{request_id}/comments",
            json={"body": " Взяли в работу "},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["body"], "Взяли в работу")
        self.assertEqual(
            self.client.get(f"/requests/{request_id}/comments").json()[0][
                "author_name"
            ],
            "Администратор",
        )

    def test_upload_contract_and_validation_are_preserved(self) -> None:
        created = self.create_public_repair([
            ("photos", ("machine.jpg", b"jpeg-data", "image/jpeg")),
        ])
        self.assertEqual(created["attachment_count"], 1)
        attachment = created["attachments"][0]
        stored_files = list(Path(self.temp_dir.name).iterdir())
        self.assertEqual(len(stored_files), 1)

        bad_type = self.client.post(
            "/public/requests",
            data=REPAIR_PAYLOAD,
            files=[("photos", ("note.txt", b"text", "text/plain"))],
        )
        self.assertEqual(bad_type.status_code, 422)
        too_many = [
            ("photos", (f"{index}.jpg", b"x", "image/jpeg"))
            for index in range(6)
        ]
        self.assertEqual(
            self.client.post(
                "/public/requests",
                data=REPAIR_PAYLOAD,
                files=too_many,
            ).status_code,
            422,
        )

        response = self.client.get(
            f"/requests/{created['id']}/attachments/{attachment['id']}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"jpeg-data")

    def test_department_list_is_exact(self) -> None:
        self.assertEqual(
            DEPARTMENTS,
            {"М15", "М35", "М6А", "Цех ГХ", "Бар ГХ", "Кухня", "Авто"},
        )

    def test_migrations_have_single_head(self) -> None:
        config = Config()
        config.set_main_option(
            "script_location",
            str(Path(__file__).resolve().parents[1] / "alembic"),
        )
        self.assertEqual(len(ScriptDirectory.from_config(config).get_heads()), 1)


if __name__ == "__main__":
    unittest.main()
