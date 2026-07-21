import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.automation.timeouts import (
    EXECUTION_TIMEOUT_CODE,
    EXECUTION_TIMEOUT_MESSAGE,
    expire_stale_executions,
    timeout_statement,
)
from app.models.automation import (
    AutomationExecution,
    ExecutionStatus,
)


NOW = datetime(2026, 7, 20, 9, 30, tzinfo=timezone.utc)


class FakeTransaction:
    def __enter__(self) -> "FakeTransaction":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        pass


class FakeScalarResult:
    def __init__(
        self,
        executions: list[AutomationExecution],
    ) -> None:
        self._executions = executions

    def all(self) -> list[AutomationExecution]:
        return self._executions


class FakeSession:
    def __init__(
        self,
        executions: list[AutomationExecution],
    ) -> None:
        self.executions = executions
        self.statement = None

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        pass

    def begin(self) -> FakeTransaction:
        return FakeTransaction()

    def scalars(self, statement) -> FakeScalarResult:
        self.statement = statement
        return FakeScalarResult(self.executions)


def make_running_execution() -> AutomationExecution:
    return AutomationExecution(
        id=1,
        execution_id=uuid4(),
        contract_version="1.0",
        automation_type="test_notification",
        tenant_id="enterpriseos",
        scope_type="company",
        scope_id=None,
        recipients=[],
        status=ExecutionStatus.RUNNING,
        requested_at=NOW - timedelta(minutes=10),
        updated_at=NOW - timedelta(minutes=10),
        payload={},
        result={"temporary": True},
        attempt_count=1,
        max_attempts=3,
        next_retry_at=NOW + timedelta(minutes=1),
    )


class ExecutionTimeoutTests(unittest.TestCase):
    def test_marks_stale_running_execution_as_timed_out(self) -> None:
        execution = make_running_execution()
        session = FakeSession([execution])

        expired_ids = expire_stale_executions(
            lambda: session,
            now=NOW,
            timeout=timedelta(minutes=5),
        )

        self.assertEqual(expired_ids, [execution.execution_id])
        self.assertEqual(
            execution.status,
            ExecutionStatus.TIMED_OUT,
        )
        self.assertEqual(execution.finished_at, NOW)
        self.assertIsNone(execution.result)
        self.assertEqual(
            execution.error_code,
            EXECUTION_TIMEOUT_CODE,
        )
        self.assertEqual(
            execution.error_message,
            EXECUTION_TIMEOUT_MESSAGE,
        )
        self.assertIsNone(execution.next_retry_at)

    def test_query_uses_skip_locked(self) -> None:
        statement = timeout_statement(
            NOW,
            timeout=timedelta(minutes=5),
            limit=25,
        )

        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("FOR UPDATE SKIP LOCKED", compiled)
        self.assertIn("LIMIT 25", compiled)
        self.assertIn("running", compiled)

    def test_rejects_invalid_timeout_and_limit(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "timeout must be positive",
        ):
            timeout_statement(
                NOW,
                timeout=timedelta(0),
            )

        with self.assertRaisesRegex(
            ValueError,
            "limit must be at least 1",
        ):
            timeout_statement(
                NOW,
                timeout=timedelta(minutes=5),
                limit=0,
            )


if __name__ == "__main__":
    unittest.main()
