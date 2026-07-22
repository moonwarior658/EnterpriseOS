import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.dependencies import get_current_admin
from app.automation.dispatch import (
    AutomationScheduleNotFoundError,
    DisabledAutomationScheduleError,
    ManualRunNotSupportedError,
)
from app.automation.schedules import InvalidScheduleScopeError
from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.automation import (
    AutomationExecution,
    AutomationSchedule,
    ExecutionStatus,
)
from app.models.user import User


CALLBACK_TOKEN = "test-callback-token"
EXECUTION_ID = UUID("41644d7a-8875-4f35-a493-371b330fb154")
NOW = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)


def make_user(*, is_admin: bool) -> User:
    return User(
        id=7 if is_admin else 8,
        username="admin" if is_admin else "employee",
        display_name="Administrator" if is_admin else "Employee",
        hashed_password="unused",
        is_active=True,
        is_admin=is_admin,
        created_at=NOW,
    )


def make_schedule(
    schedule_id: int = 42,
    *,
    name: str = "Daily report",
) -> AutomationSchedule:
    return AutomationSchedule(
        id=schedule_id,
        name=name,
        automation_type="daily_report",
        contract_version="1.0",
        tenant_id="eclair",
        scope_type="company",
        scope_id=None,
        schedule_config={"type": "daily", "time": "08:30"},
        payload={"report": "sales"},
        recipients=[{"user_id": 7}],
        timezone="Asia/Yekaterinburg",
        is_enabled=False,
        next_run_at=None,
        created_by_user_id=7,
        created_at=NOW,
        updated_at=NOW,
    )


def make_execution(schedule_id: int = 42) -> AutomationExecution:
    return AutomationExecution(
        id=101,
        execution_id=EXECUTION_ID,
        schedule_id=schedule_id,
        contract_version="1.0",
        automation_type="daily_report",
        tenant_id="eclair",
        scope_type="company",
        scope_id=None,
        recipients=[{"user_id": 7}],
        provider=None,
        status=ExecutionStatus.PENDING,
        requested_at=NOW,
        started_at=None,
        finished_at=None,
        payload={"report": "sales"},
        result=None,
        error_code=None,
        error_message=None,
        attempt_count=0,
        max_attempts=3,
        next_retry_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def valid_create_body() -> dict[str, object]:
    return {
        "name": "Daily report",
        "automation_type": "smoke_test",
        "scope_type": "company",
        "scope_id": None,
        "schedule_config": {"type": "daily", "time": "08:30"},
        "payload": {"report": "sales"},
        "recipients": [{"user_id": 7}],
        "timezone": "Asia/Yekaterinburg",
        "is_enabled": False,
    }


def valid_callback_body() -> dict[str, object]:
    return {
        "contract_version": "1.0",
        "execution_id": str(EXECUTION_ID),
        "status": "succeeded",
        "started_at": "2026-07-21T10:00:00Z",
        "finished_at": "2026-07-21T10:01:00Z",
        "result": {},
        "error_code": None,
        "error_message": None,
    }


class FakeSession:
    def __init__(self) -> None:
        self.current_user: User | None = None
        self.execution = None
        self.commit_count = 0
        self.rollback_count = 0
        self.refreshed: list[object] = []

    def get(self, model, identity):
        if model is User:
            if (
                self.current_user is not None
                and self.current_user.id == identity
            ):
                return self.current_user
            return None

        return None

    def scalar(self, statement):
        return self.execution

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def refresh(self, instance: object) -> None:
        self.refreshed.append(instance)


class AutomationSchedulesApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.previous_callback_token = settings.automation_callback_token
        settings.automation_callback_token = SecretStr(CALLBACK_TOKEN)
        self.session = FakeSession()
        self.admin = make_user(is_admin=True)
        self.employee = make_user(is_admin=False)

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        settings.automation_callback_token = self.previous_callback_token

    def authorize_as_admin(self) -> None:
        def override_current_admin() -> User:
            return self.admin

        app.dependency_overrides[get_current_admin] = override_current_admin

    def auth_headers(self, user: User) -> dict[str, str]:
        self.session.current_user = user
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}


class AutomationScheduleAuthorizationTests(AutomationSchedulesApiTestCase):
    def test_types_without_jwt_returns_401(self) -> None:
        response = self.client.get("/automation/types")

        self.assertEqual(response.status_code, 401)

    def test_get_list_without_jwt_returns_401(self) -> None:
        response = self.client.get("/automation/schedules")

        self.assertEqual(response.status_code, 401)

    def test_post_without_jwt_returns_401(self) -> None:
        response = self.client.post(
            "/automation/schedules",
            json=valid_create_body(),
        )

        self.assertEqual(response.status_code, 401)

    def test_patch_without_jwt_returns_401(self) -> None:
        response = self.client.patch(
            "/automation/schedules/42",
            json={"name": "Updated"},
        )

        self.assertEqual(response.status_code, 401)

    def test_delete_without_jwt_returns_401(self) -> None:
        response = self.client.delete("/automation/schedules/42")

        self.assertEqual(response.status_code, 401)

    def test_manual_run_without_jwt_returns_401(self) -> None:
        response = self.client.post("/automation/schedules/42/run")

        self.assertEqual(response.status_code, 401)

    def test_audit_without_jwt_returns_401(self) -> None:
        response = self.client.get("/automation/schedules/42/audit")

        self.assertEqual(response.status_code, 401)

    def test_active_non_admin_returns_403(self) -> None:
        with patch(
            "app.api.routes.automation.list_schedules"
        ) as service:
            response = self.client.get(
                "/automation/schedules",
                headers=self.auth_headers(self.employee),
            )

        self.assertEqual(response.status_code, 403)
        service.assert_not_called()

    def test_types_active_non_admin_returns_403(self) -> None:
        response = self.client.get(
            "/automation/types",
            headers=self.auth_headers(self.employee),
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_gets_access(self) -> None:
        with patch(
            "app.api.routes.automation.list_schedules",
            return_value=[],
        ):
            response = self.client.get(
                "/automation/schedules",
                headers=self.auth_headers(self.admin),
            )

        self.assertEqual(response.status_code, 200)

    def test_callback_uses_service_token_without_admin_jwt(self) -> None:
        response = self.client.post(
            "/automation/callback",
            json=valid_callback_body(),
            headers={"Authorization": f"Bearer {CALLBACK_TOKEN}"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Automation execution not found"},
        )


class AutomationScheduleListApiTests(AutomationSchedulesApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorize_as_admin()

    def test_empty_list_returns_200(self) -> None:
        with patch(
            "app.api.routes.automation.list_schedules",
            return_value=[],
        ):
            response = self.client.get("/automation/schedules")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_multiple_orm_schedules_are_serialized(self) -> None:
        schedules = [make_schedule(1), make_schedule(2, name="Weekly report")]

        with patch(
            "app.api.routes.automation.list_schedules",
            return_value=schedules,
        ):
            response = self.client.get("/automation/schedules")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [1, 2])
        self.assertEqual(response.json()[1]["name"], "Weekly report")

    def test_read_response_contains_server_fields(self) -> None:
        with patch(
            "app.api.routes.automation.list_schedules",
            return_value=[make_schedule()],
        ):
            response = self.client.get("/automation/schedules")

        item = response.json()[0]
        expected_fields = {
            "id",
            "contract_version",
            "tenant_id",
            "next_run_at",
            "created_by_user_id",
            "created_at",
            "updated_at",
        }
        self.assertTrue(expected_fields.issubset(item))

    def test_list_service_is_called_once(self) -> None:
        with patch(
            "app.api.routes.automation.list_schedules",
            return_value=[],
        ) as service:
            self.client.get("/automation/schedules")

        service.assert_called_once_with(self.session)


class AutomationTypeCatalogApiTests(AutomationSchedulesApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorize_as_admin()

    def test_admin_receives_safe_available_catalog(self) -> None:
        response = self.client.get("/automation/types")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["key"] for item in response.json()],
            ["smoke_test"],
        )
        self.assertEqual(
            response.json()[0]["display_name"],
            "Проверка Automation Core",
        )
        forbidden_fields = {
            "is_available",
            "payload",
            "handler",
            "workflow_id",
            "webhook_url",
            "provider_config",
        }
        self.assertTrue(forbidden_fields.isdisjoint(response.json()[0]))


class AutomationScheduleCreateApiTests(AutomationSchedulesApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorize_as_admin()

    def test_valid_create_returns_201(self) -> None:
        with patch(
            "app.api.routes.automation.create_schedule",
            return_value=make_schedule(),
        ):
            response = self.client.post(
                "/automation/schedules",
                json=valid_create_body(),
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], 42)

    def test_creator_comes_from_current_admin_and_service_called_once(
        self,
    ) -> None:
        with patch(
            "app.api.routes.automation.create_schedule",
            return_value=make_schedule(),
        ) as service:
            self.client.post(
                "/automation/schedules",
                json=valid_create_body(),
            )

        service.assert_called_once()
        args, kwargs = service.call_args
        self.assertIs(args[0], self.session)
        self.assertEqual(args[1].name, "Daily report")
        self.assertEqual(kwargs, {"created_by_user_id": self.admin.id})

    def test_tenant_id_cannot_be_sent_by_client(self) -> None:
        body = valid_create_body()
        body["tenant_id"] = "attacker-tenant"

        with patch(
            "app.api.routes.automation.create_schedule"
        ) as service:
            response = self.client.post(
                "/automation/schedules",
                json=body,
            )

        self.assertEqual(response.status_code, 422)
        service.assert_not_called()

    def test_server_fields_cannot_be_sent_by_client(self) -> None:
        fields = {
            "id": 1,
            "contract_version": "1.0",
            "next_run_at": "2026-07-22T05:00:00Z",
            "created_by_user_id": 99,
            "created_at": "2026-07-21T10:00:00Z",
            "updated_at": "2026-07-21T10:00:00Z",
        }

        for field, value in fields.items():
            with self.subTest(field=field):
                body = valid_create_body()
                body[field] = value

                with patch(
                    "app.api.routes.automation.create_schedule"
                ) as service:
                    response = self.client.post(
                        "/automation/schedules",
                        json=body,
                    )

                self.assertEqual(response.status_code, 422)
                service.assert_not_called()

    def test_invalid_body_returns_422(self) -> None:
        body = valid_create_body()
        body["name"] = "   "

        with patch(
            "app.api.routes.automation.create_schedule"
        ) as service:
            response = self.client.post(
                "/automation/schedules",
                json=body,
            )

        self.assertEqual(response.status_code, 422)
        service.assert_not_called()

    def test_unknown_automation_type_returns_422(self) -> None:
        body = valid_create_body()
        body["automation_type"] = "unknown_type"

        with patch("app.api.routes.automation.create_schedule") as service:
            response = self.client.post("/automation/schedules", json=body)

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("catalog", response.text.lower())
        service.assert_not_called()


class AutomationScheduleReadApiTests(AutomationSchedulesApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorize_as_admin()

    def test_existing_schedule_returns_200(self) -> None:
        with patch(
            "app.api.routes.automation.get_schedule",
            return_value=make_schedule(),
        ):
            response = self.client.get("/automation/schedules/42")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 42)

    def test_missing_schedule_returns_404(self) -> None:
        with patch(
            "app.api.routes.automation.get_schedule",
            return_value=None,
        ):
            response = self.client.get("/automation/schedules/42")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Automation schedule not found"},
        )

    def test_get_service_receives_schedule_id(self) -> None:
        with patch(
            "app.api.routes.automation.get_schedule",
            return_value=make_schedule(73),
        ) as service:
            self.client.get("/automation/schedules/73")

        service.assert_called_once_with(self.session, 73)


class AutomationScheduleUpdateApiTests(AutomationSchedulesApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorize_as_admin()

    def test_partial_update_returns_200_and_passes_object_and_payload(
        self,
    ) -> None:
        schedule = make_schedule()

        def apply_update(session, target, payload, *, actor_user_id):
            self.assertEqual(actor_user_id, self.admin.id)
            target.name = payload.name
            return target

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=schedule,
            ),
            patch(
                "app.api.routes.automation.update_schedule",
                side_effect=apply_update,
            ) as service,
        ):
            response = self.client.patch(
                "/automation/schedules/42",
                json={"name": "Updated report"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Updated report")
        args = service.call_args.args
        self.assertIs(args[0], self.session)
        self.assertIs(args[1], schedule)
        self.assertEqual(
            args[2].model_dump(exclude_unset=True),
            {"name": "Updated report"},
        )
        self.assertEqual(service.call_args.kwargs, {"actor_user_id": 7})

    def test_empty_patch_is_allowed(self) -> None:
        schedule = make_schedule()

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=schedule,
            ),
            patch(
                "app.api.routes.automation.update_schedule",
                return_value=schedule,
            ) as service,
        ):
            response = self.client.patch(
                "/automation/schedules/42",
                json={},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            service.call_args.args[2].model_dump(exclude_unset=True),
            {},
        )

    def test_missing_schedule_returns_404_without_update(self) -> None:
        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=None,
            ),
            patch(
                "app.api.routes.automation.update_schedule"
            ) as update,
        ):
            response = self.client.patch(
                "/automation/schedules/42",
                json={"name": "Updated report"},
            )

        self.assertEqual(response.status_code, 404)
        update.assert_not_called()

    def test_invalid_scope_error_returns_422(self) -> None:
        message = (
            "Invalid schedule scope: company requires scope_id to be null"
        )

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=make_schedule(),
            ),
            patch(
                "app.api.routes.automation.update_schedule",
                side_effect=InvalidScheduleScopeError(message),
            ),
        ):
            response = self.client.patch(
                "/automation/schedules/42",
                json={"scope_id": "department-1"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": message})

    def test_tenant_id_cannot_be_updated(self) -> None:
        with patch(
            "app.api.routes.automation.get_schedule"
        ) as get_service:
            response = self.client.patch(
                "/automation/schedules/42",
                json={"tenant_id": "attacker-tenant"},
            )

        self.assertEqual(response.status_code, 422)
        get_service.assert_not_called()

    def test_technical_fields_cannot_be_updated(self) -> None:
        fields = {
            "id": 1,
            "contract_version": "1.0",
            "next_run_at": "2026-07-22T05:00:00Z",
            "created_by_user_id": 99,
            "created_at": "2026-07-21T10:00:00Z",
            "updated_at": "2026-07-21T10:00:00Z",
        }

        for field, value in fields.items():
            with self.subTest(field=field):
                with patch(
                    "app.api.routes.automation.get_schedule"
                ) as get_service:
                    response = self.client.patch(
                        "/automation/schedules/42",
                        json={field: value},
                    )

                self.assertEqual(response.status_code, 422)
                get_service.assert_not_called()

    def test_unknown_automation_type_returns_422(self) -> None:
        with patch(
            "app.api.routes.automation.get_schedule"
        ) as get_service:
            response = self.client.patch(
                "/automation/schedules/42",
                json={"automation_type": "unknown_type"},
            )

        self.assertEqual(response.status_code, 422)
        get_service.assert_not_called()


class AutomationScheduleDeleteApiTests(AutomationSchedulesApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorize_as_admin()

    def test_successful_delete_returns_empty_204_and_passes_object(self) -> None:
        schedule = make_schedule()

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=schedule,
            ),
            patch(
                "app.api.routes.automation.delete_schedule"
            ) as service,
        ):
            response = self.client.delete("/automation/schedules/42")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        service.assert_called_once_with(self.session, schedule)

    def test_missing_schedule_returns_404(self) -> None:
        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=None,
            ),
            patch(
                "app.api.routes.automation.delete_schedule"
            ) as service,
        ):
            response = self.client.delete("/automation/schedules/42")

        self.assertEqual(response.status_code, 404)
        service.assert_not_called()

    def test_repeated_delete_returns_404_after_first_delete(self) -> None:
        schedule = make_schedule()

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                side_effect=[schedule, None],
            ),
            patch(
                "app.api.routes.automation.delete_schedule"
            ) as service,
        ):
            first = self.client.delete("/automation/schedules/42")
            second = self.client.delete("/automation/schedules/42")

        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 404)
        service.assert_called_once_with(self.session, schedule)


class AutomationScheduleManualRunApiTests(AutomationSchedulesApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorize_as_admin()

    def test_successful_manual_run_returns_created_execution(self) -> None:
        execution = make_execution()

        with (
            patch(
                "app.api.routes.automation.dispatch_schedule_now",
                return_value=execution,
            ) as dispatch,
        ):
            response = self.client.post("/automation/schedules/42/run")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(response.json()["schedule_id"], 42)
        dispatch.assert_called_once_with(
            self.session, 42, actor_user_id=self.admin.id
        )

    def test_missing_schedule_service_error_returns_404(self) -> None:
        with (
            patch(
                "app.api.routes.automation.dispatch_schedule_now",
                side_effect=AutomationScheduleNotFoundError,
            ) as dispatch,
        ):
            response = self.client.post("/automation/schedules/404/run")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Automation schedule not found"},
        )
        dispatch.assert_called_once_with(
            self.session, 404, actor_user_id=self.admin.id
        )

    def test_disabled_schedule_service_error_returns_409(self) -> None:
        with (
            patch(
                "app.api.routes.automation.dispatch_schedule_now",
                side_effect=DisabledAutomationScheduleError,
            ) as dispatch,
        ):
            response = self.client.post("/automation/schedules/42/run")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "Disabled automation schedule cannot be started"},
        )
        dispatch.assert_called_once_with(
            self.session, 42, actor_user_id=self.admin.id
        )

    def test_unsupported_manual_run_returns_422(self) -> None:
        with patch(
            "app.api.routes.automation.dispatch_schedule_now",
            side_effect=ManualRunNotSupportedError,
        ):
            response = self.client.post("/automation/schedules/42/run")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            {"detail": "Automation type does not support manual run"},
        )

    def test_dispatch_failure_returns_safe_error(self) -> None:
        with (
            patch(
                "app.api.routes.automation.dispatch_schedule_now",
                side_effect=RuntimeError("database secret details"),
            ),
        ):
            response = self.client.post("/automation/schedules/42/run")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"detail": "Failed to start automation schedule"},
        )
        self.assertEqual(self.session.commit_count, 0)
        self.assertNotIn("secret", response.text)


class AutomationScheduleCrudRegressionTests(AutomationSchedulesApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorize_as_admin()

    def test_openapi_contains_five_crud_operations(self) -> None:
        schema = app.openapi()
        paths = schema["paths"]

        self.assertIn("get", paths["/automation/schedules"])
        self.assertIn("post", paths["/automation/schedules"])
        self.assertIn("get", paths["/automation/schedules/{schedule_id}"])
        self.assertIn("patch", paths["/automation/schedules/{schedule_id}"])
        self.assertIn("delete", paths["/automation/schedules/{schedule_id}"])

    def test_crud_routes_do_not_call_execution_components(self) -> None:
        schedule = make_schedule()

        with (
            patch(
                "app.api.routes.automation.list_schedules",
                return_value=[schedule],
            ),
            patch(
                "app.api.routes.automation.create_schedule",
                return_value=schedule,
            ),
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=schedule,
            ),
            patch(
                "app.api.routes.automation.update_schedule",
                return_value=schedule,
            ),
            patch(
                "app.api.routes.automation.delete_schedule"
            ),
            patch(
                "app.automation.dispatch.create_automation_execution"
            ) as dispatch,
            patch(
                "app.automation.providers.base."
                "AutomationProvider.send_command"
            ) as provider,
            patch(
                "app.automation.outbox.OutboxWorker.process_one"
            ) as outbox,
        ):
            responses = [
                self.client.get("/automation/schedules"),
                self.client.post(
                    "/automation/schedules",
                    json=valid_create_body(),
                ),
                self.client.get("/automation/schedules/42"),
                self.client.patch(
                    "/automation/schedules/42",
                    json={"name": "Updated report"},
                ),
                self.client.delete("/automation/schedules/42"),
            ]

        self.assertEqual(
            [response.status_code for response in responses],
            [200, 201, 200, 200, 204],
        )
        dispatch.assert_not_called()
        provider.assert_not_called()
        outbox.assert_not_called()


if __name__ == "__main__":
    unittest.main()
