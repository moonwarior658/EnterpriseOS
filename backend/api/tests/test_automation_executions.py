import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.dependencies import get_current_admin
from app.automation.executions import (
    get_execution,
    get_latest_schedule_execution,
    list_executions,
)
from app.main import app
from app.models.automation import (
    AutomationExecution,
    AutomationSchedule,
    ExecutionStatus,
)
from app.models.user import User


NOW = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
EXECUTION_ID = UUID("41644d7a-8875-4f35-a493-371b330fb154")


def make_admin() -> User:
    return User(
        id=7,
        username="admin",
        display_name="Administrator",
        hashed_password="hash",
        is_active=True,
        is_admin=True,
        created_at=NOW,
    )


def make_execution(
    *,
    execution_id: UUID = EXECUTION_ID,
    schedule_id: int = 42,
    requested_at: datetime = NOW,
) -> AutomationExecution:
    return AutomationExecution(
        id=10,
        execution_id=execution_id,
        schedule_id=schedule_id,
        contract_version="1.0",
        automation_type="daily_report",
        tenant_id="eclair",
        scope_type="department",
        scope_id="department-7",
        recipients=[{"user_id": 7}],
        provider="n8n",
        status=ExecutionStatus.SUCCEEDED,
        requested_at=requested_at,
        started_at=NOW + timedelta(seconds=1),
        finished_at=NOW + timedelta(minutes=1),
        payload={"secret_business_input": True},
        result={"document_id": 123},
        error_code=None,
        error_message=None,
        attempt_count=1,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW + timedelta(minutes=1),
    )


def make_schedule() -> AutomationSchedule:
    return AutomationSchedule(
        id=42,
        name="Daily report",
        automation_type="daily_report",
        tenant_id="eclair",
        scope_type="department",
        scope_id="department-7",
        schedule_config={"type": "daily", "time": "09:00"},
        payload={},
        recipients=[],
        timezone="UTC",
        is_enabled=True,
        created_by_user_id=7,
    )


class ScalarCollection:
    def __init__(self, values: list[AutomationExecution]) -> None:
        self.values = values

    def all(self) -> list[AutomationExecution]:
        return self.values


class FakeSession:
    def __init__(
        self,
        *,
        values: list[AutomationExecution] | None = None,
        scalar: AutomationExecution | None = None,
    ) -> None:
        self.values = values or []
        self.scalar_value = scalar
        self.statement = None

    def scalars(self, statement: object) -> ScalarCollection:
        self.statement = statement
        return ScalarCollection(self.values)

    def scalar(self, statement: object) -> AutomationExecution | None:
        self.statement = statement
        return self.scalar_value


class ExecutionServiceTests(unittest.TestCase):
    def test_list_filters_sorts_and_pages(self) -> None:
        session = FakeSession(values=[make_execution()])

        result = list_executions(
            session,
            schedule_id=42,
            status=ExecutionStatus.SUCCEEDED,
            limit=25,
            offset=10,
        )
        compiled = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIs(result, session.values)
        self.assertIn("schedule_id = 42", compiled)
        self.assertIn("status = 'succeeded'", compiled)
        self.assertIn("requested_at DESC", compiled)
        self.assertIn("automation_executions.id DESC", compiled)
        self.assertIn("LIMIT 25 OFFSET 10", compiled)

    def test_get_uses_public_execution_uuid(self) -> None:
        expected = make_execution()
        session = FakeSession(scalar=expected)

        result = get_execution(session, EXECUTION_ID)
        compiled = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIs(result, expected)
        self.assertIn(str(EXECUTION_ID), compiled)

    def test_latest_orders_newest_first_and_limits_one(self) -> None:
        session = FakeSession(scalar=make_execution())

        get_latest_schedule_execution(session, 42)
        compiled = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("schedule_id = 42", compiled)
        self.assertIn("requested_at DESC", compiled)
        self.assertIn("LIMIT 1", compiled)


class ExecutionHistoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None

    def authorize_admin(self) -> None:
        app.dependency_overrides[get_current_admin] = make_admin

    def test_list_without_jwt_returns_401(self) -> None:
        response = self.client.get("/automation/executions")

        self.assertEqual(response.status_code, 401)

    def test_non_admin_returns_403(self) -> None:
        def deny_admin() -> None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator access required",
            )

        app.dependency_overrides[get_current_admin] = deny_admin

        response = self.client.get("/automation/executions")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_read_empty_list(self) -> None:
        self.authorize_admin()

        with patch(
            "app.api.routes.automation.list_executions",
            return_value=[],
        ):
            response = self.client.get("/automation/executions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_passes_filters_and_pagination(self) -> None:
        self.authorize_admin()

        with patch(
            "app.api.routes.automation.list_executions",
            return_value=[make_execution()],
        ) as service:
            response = self.client.get(
                "/automation/executions",
                params={
                    "schedule_id": 42,
                    "status": "succeeded",
                    "limit": 25,
                    "offset": 10,
                },
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once()
        kwargs = service.call_args.kwargs
        self.assertEqual(kwargs["schedule_id"], 42)
        self.assertEqual(kwargs["status"].value, "succeeded")
        self.assertEqual(kwargs["limit"], 25)
        self.assertEqual(kwargs["offset"], 10)

    def test_limit_over_100_and_invalid_status_return_422(self) -> None:
        self.authorize_admin()

        for params in ({"limit": 101}, {"status": "unknown"}):
            with self.subTest(params=params):
                response = self.client.get(
                    "/automation/executions",
                    params=params,
                )
                self.assertEqual(response.status_code, 422)

    def test_get_existing_and_missing_execution(self) -> None:
        self.authorize_admin()

        with patch(
            "app.api.routes.automation.get_execution",
            return_value=make_execution(),
        ):
            existing = self.client.get(
                f"/automation/executions/{EXECUTION_ID}"
            )
        with patch(
            "app.api.routes.automation.get_execution",
            return_value=None,
        ):
            missing = self.client.get(
                f"/automation/executions/{EXECUTION_ID}"
            )

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(missing.status_code, 404)

    def test_schedule_history_and_missing_schedule(self) -> None:
        self.authorize_admin()

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=make_schedule(),
            ),
            patch(
                "app.api.routes.automation.list_executions",
                return_value=[make_execution()],
            ) as service,
        ):
            response = self.client.get(
                "/automation/schedules/42/executions?limit=10&offset=2"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.call_args.kwargs["schedule_id"], 42)
        self.assertEqual(service.call_args.kwargs["limit"], 10)
        self.assertEqual(service.call_args.kwargs["offset"], 2)

        with patch(
            "app.api.routes.automation.get_schedule",
            return_value=None,
        ):
            missing = self.client.get(
                "/automation/schedules/404/executions"
            )
        self.assertEqual(missing.status_code, 404)

    def test_latest_returns_execution_or_null(self) -> None:
        self.authorize_admin()

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=make_schedule(),
            ),
            patch(
                "app.api.routes.automation.get_latest_schedule_execution",
                side_effect=[make_execution(), None],
            ),
        ):
            existing = self.client.get(
                "/automation/schedules/42/executions/latest"
            )
            empty = self.client.get(
                "/automation/schedules/42/executions/latest"
            )

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(empty.status_code, 200)
        self.assertIsNone(empty.json())

    def test_latest_returns_404_for_missing_schedule(self) -> None:
        self.authorize_admin()

        with patch(
            "app.api.routes.automation.get_schedule",
            return_value=None,
        ):
            response = self.client.get(
                "/automation/schedules/404/executions/latest"
            )

        self.assertEqual(response.status_code, 404)

    def test_response_contains_snapshot_and_no_sensitive_fields(self) -> None:
        self.authorize_admin()

        with patch(
            "app.api.routes.automation.get_execution",
            return_value=make_execution(),
        ):
            response = self.client.get(
                f"/automation/executions/{EXECUTION_ID}"
            )

        body = response.json()
        self.assertEqual(body["scope_type"], "department")
        self.assertEqual(body["scope_id"], "department-7")
        self.assertEqual(body["recipients"], [{"user_id": 7}])
        for field in ("payload", "result", "tenant_id", "outbox_events"):
            self.assertNotIn(field, body)

    def test_openapi_contains_history_routes(self) -> None:
        paths = self.client.get("/openapi.json").json()["paths"]

        self.assertIn("/automation/executions", paths)
        self.assertIn("/automation/executions/{execution_id}", paths)
        self.assertIn(
            "/automation/schedules/{schedule_id}/executions",
            paths,
        )
        self.assertIn(
            "/automation/schedules/{schedule_id}/executions/latest",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
