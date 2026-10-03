"""Employee avatar upload, normalization, persistence reference, and RBAC."""
from io import BytesIO
import tempfile
from uuid import UUID

from PIL import Image
from sqlalchemy import select

from app.api.routes.employees import settings
from app.models.audit import AuditEvent
from app.models.employee import Employee
from tests.test_employees_api import EmployeesApiTests


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (900, 700), "#cc8844").save(output, format="JPEG")
    return output.getvalue()


class EmployeeAvatarTests(EmployeesApiTests):
    def setUp(self) -> None:
        super().setUp()
        self.avatar_dir = tempfile.TemporaryDirectory()
        self.previous_avatar_dir = settings.employee_avatar_upload_dir
        settings.employee_avatar_upload_dir = self.avatar_dir.name

    def tearDown(self) -> None:
        settings.employee_avatar_upload_dir = self.previous_avatar_dir
        self.avatar_dir.cleanup()
        super().tearDown()

    def test_upload_replace_invalid_type_and_delete(self) -> None:
        employee_id = self.create_employee()["id"]
        uploaded = self.client.post(f"/employees/{employee_id}/avatar",
            files={"photo": ("photo.jpg", image_bytes(), "image/jpeg")})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["photo_url"], "employee-avatar")
        stored = settings.employee_avatar_upload_dir + f"/{employee_id}/avatar.webp"
        with Image.open(stored) as image:
            self.assertLessEqual(max(image.size), 512)
            self.assertEqual(image.format, "WEBP")
        self.assertEqual(self.client.get(f"/employees/{employee_id}/avatar").status_code, 200)
        replaced = self.client.post(f"/employees/{employee_id}/avatar",
            files={"photo": ("replacement.png", image_bytes(), "image/png")})
        self.assertEqual(replaced.status_code, 200, replaced.text)
        invalid = self.client.post(f"/employees/{employee_id}/avatar",
            files={"photo": ("photo.heic", b"not-an-image", "image/heic")})
        self.assertEqual(invalid.status_code, 422)
        deleted = self.client.delete(f"/employees/{employee_id}/avatar")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertIsNone(deleted.json()["photo_url"])
        with self.sessions() as session:
            events = list(session.scalars(select(AuditEvent).where(
                AuditEvent.entity_id == employee_id,
                AuditEvent.event_type.in_(("EMPLOYEE_AVATAR_UPDATED", "EMPLOYEE_AVATAR_REMOVED")),
            )).all())
            self.assertEqual(len(events), 3)
            self.assertTrue(all(item.reason is None for item in events))
            self.assertTrue(all("binary" not in str(item.after).lower() for item in events))

    def test_linked_human_can_update_own_avatar(self) -> None:
        employee_id = self.create_employee()["id"]
        created = self.client.post("/users", json={"username": "avatar.owner",
            "display_name": "Avatar Owner", "account_type": "HUMAN", "employee_id": employee_id})
        self.assertEqual(created.status_code, 201, created.text)
        self.client.post(f"/employees/{employee_id}/roles", json={
            "role": "SELLER", "valid_from": "2026-01-01T00:00:00+00:00", "reason": "Работа",
        })
        self.current_user_id = created.json()["id"]
        uploaded = self.client.post(f"/employees/{employee_id}/avatar",
            files={"photo": ("photo.png", image_bytes(), "image/png")})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(self.client.get(f"/employees/{employee_id}/avatar").status_code, 200)
        with self.sessions() as session:
            self.assertEqual(session.get(Employee, UUID(employee_id)).photo_url, "employee-avatar")
