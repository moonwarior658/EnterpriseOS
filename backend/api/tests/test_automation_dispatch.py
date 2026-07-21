import unittest

from app.automation.dispatch import (
    AUTOMATION_COMMAND_EVENT_TYPE,
    create_automation_execution,
)
from app.models.automation import (
    AutomationExecution,
    ExecutionStatus,
    OutboxEvent,
    OutboxStatus,
)


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    def __enter__(self) -> "FakeTransaction":
        self._session.transaction_open = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        self._session.transaction_open = False

        if exc_type is None:
            self._session.committed.extend(self._session.staged)
            self._session.commit_count += 1
        else:
            self._session.rollback_count += 1

        self._session.staged.clear()


class FakeNestedTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    def __enter__(self) -> "FakeNestedTransaction":
        if not self._session.transaction_open:
            raise AssertionError("Nested transaction requires outer transaction")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        if exc_type is not None:
            self._session.staged.clear()


class FakeSession:
    def __init__(self, *, fail_on_flush: bool = False) -> None:
        self.fail_on_flush = fail_on_flush
        self.transaction_open = False
        self.staged: list[object] = []
        self.committed: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.nested_begin_count = 0

    def in_transaction(self) -> bool:
        return self.transaction_open

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    def begin_nested(self) -> FakeNestedTransaction:
        self.nested_begin_count += 1
        return FakeNestedTransaction(self)

    def add_all(self, instances: list[object]) -> None:
        if not self.transaction_open:
            raise AssertionError("Records added outside transaction")
        self.staged.extend(instances)

    def flush(self) -> None:
        if not self.transaction_open:
            raise AssertionError("Flush called outside transaction")
        if self.fail_on_flush:
            raise RuntimeError("database write failed")


class AutomationDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = FakeSession()

    def create_execution(self) -> AutomationExecution:
        return create_automation_execution(
            self.session,
            automation_type="daily_sales_report",
            tenant_id="tenant-42",
            scope_type="department",
            scope_id="department-7",
            recipients=[{"user_id": 10}],
            payload={"location_ids": [10, 20]},
        )

    def test_creates_linked_execution_and_outbox_event(self) -> None:
        execution = self.create_execution()

        self.assertEqual(len(self.session.committed), 2)
        stored_execution = self.session.committed[0]
        outbox_event = self.session.committed[1]
        self.assertIs(stored_execution, execution)
        self.assertIsInstance(outbox_event, OutboxEvent)
        self.assertIs(outbox_event.execution, execution)
        self.assertEqual(outbox_event.execution_id, execution.execution_id)
        self.assertIn(outbox_event, execution.outbox_events)
        self.assertEqual(self.session.commit_count, 1)

    def test_values_and_pending_statuses_are_correct(self) -> None:
        execution = self.create_execution()
        outbox_event = self.session.committed[1]

        self.assertEqual(execution.status, ExecutionStatus.PENDING)
        self.assertEqual(execution.contract_version, "1.0")
        self.assertEqual(execution.automation_type, "daily_sales_report")
        self.assertEqual(execution.tenant_id, "tenant-42")
        self.assertEqual(execution.scope_type, "department")
        self.assertEqual(execution.scope_id, "department-7")
        self.assertEqual(execution.recipients, [{"user_id": 10}])
        self.assertEqual(
            execution.payload,
            {"location_ids": [10, 20]},
        )
        self.assertIsNotNone(execution.execution_id)
        self.assertIsNotNone(execution.requested_at.tzinfo)

        another_execution = create_automation_execution(
            FakeSession(),
            automation_type="daily_sales_report",
            tenant_id="tenant-42",
            scope_type="company",
            scope_id=None,
            recipients=[],
            payload={},
        )

        self.assertNotEqual(
            another_execution.execution_id,
            execution.execution_id,
        )
        self.assertEqual(outbox_event.status, OutboxStatus.PENDING)
        self.assertEqual(outbox_event.contract_version, "1.0")
        self.assertEqual(
            outbox_event.event_type,
            AUTOMATION_COMMAND_EVENT_TYPE,
        )
        self.assertEqual(
            outbox_event.payload,
            {"location_ids": [10, 20]},
        )

    def test_error_rolls_back_both_records(self) -> None:
        session = FakeSession(fail_on_flush=True)

        with self.assertRaisesRegex(
            RuntimeError,
            "database write failed",
        ):
            create_automation_execution(
                session,
                automation_type="daily_sales_report",
                tenant_id="tenant-42",
                scope_type="company",
                scope_id=None,
                recipients=[],
                payload={"location_ids": [10, 20]},
            )

        self.assertEqual(session.committed, [])
        self.assertEqual(session.staged, [])
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.rollback_count, 1)
        self.assertFalse(session.transaction_open)

    def test_works_inside_existing_transaction(self) -> None:
        session = FakeSession()

        with session.begin():
            execution = create_automation_execution(
                session,
                automation_type="daily_sales_report",
                tenant_id="tenant-42",
                scope_type="company",
                scope_id=None,
                recipients=[],
                payload={"location_ids": [10, 20]},
            )

            self.assertTrue(session.transaction_open)
            self.assertEqual(session.committed, [])
            self.assertEqual(session.nested_begin_count, 1)

        self.assertEqual(len(session.committed), 2)
        self.assertIs(session.committed[0], execution)
        self.assertEqual(session.commit_count, 1)

    def test_recipients_are_snapshotted(self) -> None:
        recipients = [{"user_id": 10}]

        execution = create_automation_execution(
            self.session,
            automation_type="daily_sales_report",
            tenant_id="tenant-42",
            scope_type="department",
            scope_id="department-7",
            recipients=recipients,
            payload={},
        )
        recipients.append({"user_id": 11})
        recipients[0]["user_id"] = 99

        self.assertEqual(execution.recipients, [{"user_id": 10}])


if __name__ == "__main__":
    unittest.main()
