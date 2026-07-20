import os
import unittest
from datetime import datetime, timezone
from uuid import UUID

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.automation import AutomationExecution, ExecutionStatus


EXECUTION_ID = UUID("41644d7a-8875-4f35-a493-371b330fb154")
CALLBACK_TOKEN = "test-callback-token"
STARTED_AT = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)
FINISHED_AT = datetime(2026, 7, 20, 8, 1, tzinfo=timezone.utc)


def callback_payload(
    *,
    execution_id: UUID = EXECUTION_ID,
    status: str = "succeeded",
) -> dict[str, object]:
    return {
        "contract_version": "1.0",
        "execution_id": str(execution_id),
        "status": status,
        "started_at": STARTED_AT.isoformat(),
        "finished_at": FINISHED_AT.isoformat(),
        "result": {"document_id": 123},
        "error_code": None,
        "error_message": None,
    }


def make_execution(
    *,
    status: ExecutionStatus = ExecutionStatus.RUNNING,
) -> AutomationExecution:
    return AutomationExecution(
        id=1,
        execution_id=EXECUTION_ID,
        contract_version="1.0",
        automation_type="daily_sales_report",
        tenant_id="tenant-42",
        status=status,
        requested_at=STARTED_AT,
        payload={},
        attempt_count=1,
        max_attempts=3,
    )


class FakeSession:
    def __init__(
        self,
        execution: AutomationExecution | None,
    ) -> None:
        self.execution = execution
        self.statement = None
        self.commit_count = 0

    def scalar(self, statement):
        self.statement = statement
        return self.execution

    def commit(self) -> None:
        self.commit_count += 1


class AutomationCallbackApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_token = settings.automation_callback_token
        settings.automation_callback_token = SecretStr(CALLBACK_TOKEN)
        self.session = FakeSession(make_execution())

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        settings.automation_callback_token = self.previous_token

    def post_callback(
        self,
        payload: dict[str, object],
        *,
        token: str = CALLBACK_TOKEN,
    ):
        return self.client.post(
            "/automation/callback",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_successful_callback(self) -> None:
        response = self.post_callback(callback_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "accepted"})
        self.assertEqual(
            self.session.execution.status,
            ExecutionStatus.SUCCEEDED,
        )
        self.assertEqual(self.session.execution.started_at, STARTED_AT)
        self.assertEqual(self.session.execution.finished_at, FINISHED_AT)
        self.assertEqual(
            self.session.execution.result,
            {"document_id": 123},
        )
        self.assertIsNone(self.session.execution.error_code)
        self.assertIsNone(self.session.execution.error_message)
        self.assertEqual(self.session.commit_count, 1)

    def test_invalid_or_missing_token_returns_401(self) -> None:
        response = self.post_callback(
            callback_payload(),
            token="wrong-token",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Invalid service credentials"},
        )
        self.assertIsNone(self.session.statement)

        missing_token_response = self.client.post(
            "/automation/callback",
            json=callback_payload(),
        )

        self.assertEqual(missing_token_response.status_code, 401)
        self.assertEqual(
            missing_token_response.json(),
            {"detail": "Invalid service credentials"},
        )
        self.assertIsNone(self.session.statement)

    def test_unknown_execution_returns_404(self) -> None:
        self.session.execution = None

        response = self.post_callback(callback_payload())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.session.commit_count, 0)

    def test_identical_terminal_callback_is_idempotent(self) -> None:
        self.session.execution = make_execution(
            status=ExecutionStatus.SUCCEEDED
        )
        self.session.execution.started_at = STARTED_AT
        self.session.execution.finished_at = FINISHED_AT
        self.session.execution.result = {"document_id": 123}

        response = self.post_callback(callback_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "accepted"})
        self.assertEqual(self.session.commit_count, 0)

    def test_conflicting_callback_after_terminal_status(self) -> None:
        self.session.execution = make_execution(
            status=ExecutionStatus.SUCCEEDED
        )
        self.session.execution.started_at = STARTED_AT
        self.session.execution.finished_at = FINISHED_AT
        self.session.execution.result = {"document_id": 123}

        response = self.post_callback(
            callback_payload(status="failed")
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.session.execution.status,
            ExecutionStatus.SUCCEEDED,
        )
        self.assertEqual(self.session.commit_count, 0)

    def test_execution_query_uses_for_update(self) -> None:
        response = self.post_callback(callback_payload())

        compiled = str(
            self.session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("FOR UPDATE", compiled)


if __name__ == "__main__":
    unittest.main()
