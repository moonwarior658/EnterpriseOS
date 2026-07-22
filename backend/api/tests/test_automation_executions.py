import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, patch
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
    classify_execution_status,
    count_executions,
    get_execution,
    get_latest_schedule_execution,
    get_latest_schedule_executions,
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


class RowCollection:
    def __init__(
        self,
        values: list[tuple[int, AutomationExecution | None]],
    ) -> None:
        self.values = values

    def all(self) -> list[tuple[int, AutomationExecution | None]]:
        return self.values


class FakeSession:
    def __init__(
        self,
        *,
        values: list[AutomationExecution] | None = None,
        scalar: AutomationExecution | int | None = None,
        rows: list[tuple[int, AutomationExecution | None]] | None = None,
    ) -> None:
        self.values = values or []
        self.scalar_value = scalar
        self.rows = rows or []
        self.statement = None
        self.execute_count = 0

    def scalars(self, statement: object) -> ScalarCollection:
        self.statement = statement
        return ScalarCollection(self.values)

    def scalar(
        self,
        statement: object,
    ) -> AutomationExecution | int | None:
        self.statement = statement
        return self.scalar_value

    def execute(self, statement: object) -> RowCollection:
        self.statement = statement
        self.execute_count += 1
        return RowCollection(self.rows)


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

    def test_count_filters_by_schedule(self) -> None:
        session = FakeSession(scalar=7)

        result = count_executions(session, schedule_id=42)
        compiled = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertEqual(result, 7)
        self.assertIn("count(automation_executions.id)", compiled)
        self.assertIn("schedule_id = 42", compiled)

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

    def test_batch_latest_uses_one_ranked_query_for_all_schedules(self) -> None:
        latest = make_execution()
        session = FakeSession(rows=[(7, None), (42, latest)])

        result = get_latest_schedule_executions(session)
        compiled = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertEqual(result, [(7, None), (42, latest)])
        self.assertEqual(session.execute_count, 1)
        self.assertIn("row_number() OVER", compiled)
        self.assertIn(
            "PARTITION BY automation_executions.schedule_id",
            compiled,
        )
        self.assertIn("automation_executions.requested_at DESC", compiled)
        self.assertIn("automation_executions.id DESC", compiled)
        self.assertIn("execution_rank = 1", compiled)
        self.assertIn("LEFT OUTER JOIN", compiled)

    def test_batch_latest_filters_requested_schedules_in_same_query(self) -> None:
        session = FakeSession(rows=[(42, make_execution())])

        get_latest_schedule_executions(session, [42, 7, 42])
        compiled = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertEqual(session.execute_count, 1)
        self.assertIn("automation_schedules.id IN (7, 42)", compiled)

    def test_all_execution_statuses_have_safe_user_classification(self) -> None:
        expected = {
            ExecutionStatus.PENDING: "Ожидает запуска",
            ExecutionStatus.DISPATCHING: "Запускается",
            ExecutionStatus.RUNNING: "Выполняется",
            ExecutionStatus.RETRYING: "Ожидает повторного запуска",
            ExecutionStatus.SUCCEEDED: "Выполнено",
            ExecutionStatus.FAILED: "Ошибка выполнения",
            ExecutionStatus.TIMED_OUT: "Превышено время ожидания",
            ExecutionStatus.CANCELLED: "Отменено",
        }

        for execution_status, user_status in expected.items():
            with self.subTest(status=execution_status):
                public_state = classify_execution_status(execution_status)
                self.assertEqual(public_state.user_status, user_status)
                self.assertNotIn("http", public_state.user_message.lower())
                self.assertNotIn("exception", public_state.user_message.lower())


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

    def test_batch_latest_without_jwt_returns_401(self) -> None:
        response = self.client.get(
            "/automation/schedules/executions/latest"
        )

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

    def test_schedule_history_is_safe_and_paginated(self) -> None:
        self.authorize_admin()

        execution = make_execution()
        execution.error_code = "SECRET_PROVIDER_FAILURE"
        execution.error_message = "webhook https://secret.invalid/token"
        execution.status = ExecutionStatus.FAILED

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=make_schedule(),
            ),
            patch(
                "app.api.routes.automation.list_executions",
                return_value=[execution],
            ) as service,
            patch(
                "app.api.routes.automation.count_executions",
                return_value=13,
            ) as count_service,
        ):
            response = self.client.get(
                "/automation/schedules/42/executions?limit=10&offset=2"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 13)
        self.assertEqual(body["limit"], 10)
        self.assertEqual(body["offset"], 2)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["status"], "failed")
        self.assertEqual(body["items"][0]["duration_seconds"], 59.0)
        self.assertEqual(
            body["items"][0]["error_code"],
            "AUTOMATION_FAILED",
        )
        self.assertEqual(
            body["items"][0]["error_message"],
            "Не удалось выполнить регламент",
        )
        self.assertEqual(
            body["items"][0]["user_status"],
            "Ошибка выполнения",
        )
        self.assertEqual(
            body["items"][0]["user_message"],
            "Не удалось выполнить регламент",
        )
        self.assertEqual(
            body["items"][0]["error_category"],
            "execution_failed",
        )
        internal_fields = {
            "id",
            "execution_id",
            "schedule_id",
            "automation_type",
            "scope_type",
            "scope_id",
            "recipients",
            "provider",
            "attempt_count",
            "max_attempts",
            "payload",
            "result",
            "created_at",
            "updated_at",
            "outbox_events",
        }
        self.assertTrue(internal_fields.isdisjoint(body["items"][0]))
        self.assertEqual(service.call_args.kwargs["schedule_id"], 42)
        self.assertEqual(service.call_args.kwargs["limit"], 10)
        self.assertEqual(service.call_args.kwargs["offset"], 2)
        count_service.assert_called_once_with(
            ANY,
            schedule_id=42,
        )

    def test_schedule_history_empty(self) -> None:
        self.authorize_admin()

        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=make_schedule(),
            ),
            patch(
                "app.api.routes.automation.list_executions",
                return_value=[],
            ),
            patch(
                "app.api.routes.automation.count_executions",
                return_value=0,
            ),
        ):
            response = self.client.get(
                "/automation/schedules/42/executions"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["total"], 0)

    def test_schedule_history_returns_404_for_missing_schedule(self) -> None:
        self.authorize_admin()

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

    def test_batch_latest_returns_execution_and_schedule_without_runs(self) -> None:
        self.authorize_admin()
        execution = make_execution()

        with patch(
            "app.api.routes.automation.get_latest_schedule_executions",
            return_value=[(7, None), (42, execution)],
        ) as service:
            response = self.client.get(
                "/automation/schedules/executions/latest"
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(ANY, None)
        body = response.json()
        self.assertEqual(body[0], {
            "schedule_id": 7,
            "status": None,
            "requested_at": None,
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "user_status": "Нет запусков",
            "user_message": "Регламент ещё не запускался",
            "error_category": None,
            "error_code": None,
        })
        self.assertEqual(body[1]["schedule_id"], 42)
        self.assertEqual(body[1]["status"], "succeeded")
        self.assertEqual(body[1]["duration_seconds"], 59.0)
        self.assertEqual(body[1]["user_status"], "Выполнено")

    def test_batch_latest_accepts_multiple_schedule_ids(self) -> None:
        self.authorize_admin()

        with patch(
            "app.api.routes.automation.get_latest_schedule_executions",
            return_value=[],
        ) as service:
            response = self.client.get(
                "/automation/schedules/executions/latest",
                params=[("schedule_id", "42"), ("schedule_id", "7")],
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(ANY, [42, 7])

    def test_batch_latest_contract_excludes_internal_fields_and_errors(self) -> None:
        self.authorize_admin()
        unsafe_values = (
            "Traceback SqlError at https://n8n.invalid/webhook?token=secret"
        )
        internal_fields = {
            "id",
            "execution_id",
            "automation_type",
            "scope_type",
            "scope_id",
            "recipients",
            "provider",
            "payload",
            "result",
            "error_message",
            "outbox",
            "outbox_events",
        }

        for execution_status, expected_message in (
            (ExecutionStatus.FAILED, "Не удалось выполнить регламент"),
            (
                ExecutionStatus.TIMED_OUT,
                "Регламент не завершился за отведённое время",
            ),
            (ExecutionStatus.CANCELLED, "Запуск регламента отменён"),
        ):
            with self.subTest(status=execution_status):
                execution = make_execution()
                execution.status = execution_status
                execution.error_code = "N8N_INTERNAL_ERROR"
                execution.error_message = unsafe_values
                with patch(
                    "app.api.routes.automation.get_latest_schedule_executions",
                    return_value=[(42, execution)],
                ):
                    response = self.client.get(
                        "/automation/schedules/executions/latest"
                    )

                item = response.json()[0]
                self.assertTrue(internal_fields.isdisjoint(item))
                self.assertEqual(item["user_message"], expected_message)
                self.assertNotIn("n8n", response.text.lower())
                self.assertNotIn("secret", response.text.lower())

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
        self.assertIn(
            "/automation/schedules/executions/latest",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
